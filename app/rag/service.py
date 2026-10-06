"""Retrieval-augmented question answering with citations, groundedness and review routing.

question -> input guardrail -> retrieval (top-k, threshold, metadata filter) -> context assembly
-> LLM (versioned prompt, JSON schema) -> citation binding (only retrieved chunk ids are
accepted) -> deterministic groundedness -> output guardrails -> confidence -> review routing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.audit.service import SYSTEM_ACTOR, AuditService
from app.core.clock import new_id
from app.core.errors import InvalidStateError, ProviderError
from app.core.hashing import sha256_text
from app.core.text import clean_line, content_tokens
from app.domain.enums import ReviewReason, ReviewTargetType
from app.domain.models import (
    DEFAULT_WORKSPACE,
    Citation,
    GroundednessReport,
    RAGAnswer,
    RetrievalResult,
)
from app.guardrails.injection import scan_for_injection
from app.guardrails.policy import check_question, find_prohibited_claims
from app.human_review.service import HumanReviewService
from app.observability.logging import log_event
from app.observability.metrics import MetricsRecorder
from app.persistence.repositories import AnswerRepository, DocumentRepository
from app.providers.vectorstore.base import MetadataFilterInput
from app.rag.groundedness import check_groundedness
from app.retrieval.base import RetrievalOutcome, RetrieverProtocol
from app.services.model_gateway import ModelGateway
from app.workflows.state_machine import QUERYABLE

logger = logging.getLogger(__name__)

PROMPT_NAME = "rag.grounded_answer"
INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not find enough supporting evidence in the indexed documents to answer this question."
)
WITHHELD_ANSWER = (
    "The generated answer was withheld because it could not be verified against the cited "
    "evidence. It has been sent for human review."
)
SNIPPET_CHARS = 300


class RAGLLMOutput(BaseModel):
    answer: str = Field(max_length=4000)
    cited_chunk_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False


@dataclass(frozen=True)
class RAGSettings:
    min_answer_confidence: float
    groundedness_min: float
    retrieval_min_score: float
    retrieval_strong_score: float
    max_context_chars: int
    review_on_insufficient_evidence: bool


def best_snippet(chunk_text: str, answer: str) -> str:
    """The chunk line that best overlaps the answer, for a precise citation snippet."""
    answer_tokens = set(content_tokens(answer))
    best, best_score = "", -1
    for line in chunk_text.splitlines():
        cleaned = clean_line(line)
        if not cleaned:
            continue
        score = len(answer_tokens & set(content_tokens(cleaned)))
        if score > best_score:
            best, best_score = cleaned, score
    return (best if best_score > 0 else clean_line(chunk_text))[:SNIPPET_CHARS]


class RAGService:
    def __init__(
        self,
        retriever: RetrieverProtocol,
        gateway: ModelGateway,
        documents: DocumentRepository,
        answers: AnswerRepository,
        reviews: HumanReviewService,
        audit: AuditService,
        metrics: MetricsRecorder,
        settings: RAGSettings,
        embedding_model: str,
    ) -> None:
        self._retriever = retriever
        self._gateway = gateway
        self._documents = documents
        self._answers = answers
        self._reviews = reviews
        self._audit = audit
        self._metrics = metrics
        self._s = settings
        self._embedding_model = embedding_model

    # ------------------------------------------------------------------ public

    def ask(
        self,
        question: str,
        document_id: str | None = None,
        filters: MetadataFilterInput | None = None,
        top_k: int | None = None,
        actor: str = SYSTEM_ACTOR,
        workspace_id: str | None = None,
    ) -> RAGAnswer:
        """Answer from indexed evidence. ``workspace_id`` (demo visitors) restricts retrieval to
        that workspace and tags the answer and any review case with it."""
        warnings: list[str] = []
        if document_id is not None:
            doc = self._documents.get(document_id)
            if doc.status not in QUERYABLE:
                raise InvalidStateError(
                    f"document {document_id} is {doc.status.value}; process it before asking"
                )
            if doc.status.value == "NEEDS_REVIEW":
                warnings.append("document has a pending human review; extracted data unverified")
            if "prompt_injection_suspected" in doc.security_flags:
                warnings.append("document was flagged for suspicious embedded instructions")

        q_check = check_question(question)
        if not q_check.allowed:
            self._metrics.increment("guardrail_triggers_total", labels={"guardrail": "question"})
            self._audit.record(
                "guardrail.question_blocked",
                actor=actor,
                document_id=document_id,
                details={
                    "reason": q_check.reason,
                    "patterns": q_check.patterns,
                    "question_sha256": sha256_text(question),
                },
            )
            return self._finalize(
                self._refusal(question, document_id, q_check.reason or "blocked", warnings),
                actor,
                reasons=[],
                workspace_id=workspace_id,
            )

        retrieval = self._retriever.retrieve(
            question,
            document_id=document_id,
            filters=filters,
            top_k=top_k,
            workspace_id=workspace_id,
        )
        if not retrieval.results:
            return self._insufficient(
                question, document_id, retrieval, warnings, actor, workspace_id
            )

        context, used = self._assemble_context(retrieval.results)
        if any(scan_for_injection(r.chunk.text).flagged for r in used):
            warnings.append("retrieved context contains suspicious instructions; treated as data")

        try:
            result = self._gateway.invoke(
                PROMPT_NAME,
                render_vars={"question": question, "context": context},
                structured_vars={
                    "question": question,
                    "context_chunks": [
                        {
                            "chunk_id": r.chunk.chunk_id,
                            "text": r.chunk.text,
                            "page_number": r.chunk.page_number,
                        }
                        for r in used
                    ],
                },
                schema=RAGLLMOutput,
                operation="rag_answer",
                document_id=document_id,
            )
        except ProviderError as exc:
            answer = self._refusal(
                question, document_id, f"answer generation failed: {exc.error_type}", warnings
            )
            answer.retrieval_scores = retrieval.candidate_scores
            return self._finalize(
                answer, actor, reasons=[ReviewReason.RETRIES_EXHAUSTED], workspace_id=workspace_id
            )

        out = result.output
        base: dict[str, Any] = {
            "provider": result.invocation.provider,
            "model_name": result.invocation.model_name,
            "prompt_version": result.prompt.version,
            "is_mock": result.invocation.is_mock,
        }
        if out.insufficient_evidence:
            return self._insufficient(
                question, document_id, retrieval, warnings, actor, workspace_id, base
            )

        by_id = {r.chunk.chunk_id: r for r in used}
        cited = [by_id[cid] for cid in dict.fromkeys(out.cited_chunk_ids) if cid in by_id]
        invalid_ids = [cid for cid in out.cited_chunk_ids if cid not in by_id]
        reasons: list[ReviewReason] = []
        if invalid_ids:
            warnings.append(f"model cited {len(invalid_ids)} chunk id(s) not in retrieved context")
            self._metrics.increment(
                "guardrail_triggers_total", labels={"guardrail": "invalid_citation"}
            )

        if not cited:
            answer = self._refusal(
                question,
                document_id,
                "answer withheld: no valid citations to retrieved evidence",
                warnings,
                message=WITHHELD_ANSWER,
                **base,
            )
            answer.retrieval_scores = retrieval.candidate_scores
            return self._finalize(
                answer,
                actor,
                reasons=[ReviewReason.WEAK_GROUNDING],
                original={"answer": out.answer, "cited_chunk_ids": out.cited_chunk_ids},
                workspace_id=workspace_id,
            )

        citations = [
            Citation(
                document_id=r.chunk.document_id,
                page_number=r.chunk.page_number,
                chunk_id=r.chunk.chunk_id,
                text_snippet=best_snippet(r.chunk.text, out.answer),
                retrieval_score=r.score,
            )
            for r in cited
        ]
        grounded = check_groundedness(out.answer, [r.chunk.text for r in cited])
        confidence = self._confidence(grounded, cited)

        prohibited = find_prohibited_claims(out.answer)
        if grounded.unsupported_numbers or prohibited:
            reason = (
                f"answer withheld: figures not present in cited evidence "
                f"({', '.join(grounded.unsupported_numbers)})"
                if grounded.unsupported_numbers
                else "answer withheld: contains prohibited advice/guarantee language"
            )
            self._metrics.increment(
                "guardrail_triggers_total",
                labels={
                    "guardrail": "unsupported_figures"
                    if grounded.unsupported_numbers
                    else "prohibited_claim"
                },
            )
            answer = self._refusal(
                question, document_id, reason, warnings, message=WITHHELD_ANSWER, **base
            )
            answer.groundedness = grounded
            answer.retrieval_scores = retrieval.candidate_scores
            review_reasons = [
                ReviewReason.WEAK_GROUNDING
                if grounded.unsupported_numbers
                else ReviewReason.GUARDRAIL_TRIGGERED
            ]
            return self._finalize(
                answer,
                actor,
                reasons=review_reasons,
                original={"answer": out.answer, "cited_chunk_ids": out.cited_chunk_ids},
                workspace_id=workspace_id,
            )

        if grounded.score < self._s.groundedness_min:
            reasons.append(ReviewReason.WEAK_GROUNDING)
        if confidence < self._s.min_answer_confidence:
            reasons.append(ReviewReason.LOW_ANSWER_CONFIDENCE)
        if reasons:
            warnings.append("answer requires human review before it is relied upon")

        answer = RAGAnswer(
            answer_id=new_id("ans"),
            document_id=document_id,
            question=question,
            answer=out.answer,
            citations=citations,
            confidence=confidence,
            groundedness=grounded,
            requires_review=bool(reasons),
            warnings=warnings,
            retrieval_scores=retrieval.candidate_scores,
            embedding_model=self._embedding_model,
            **base,
        )
        return self._finalize(answer, actor, reasons=reasons, workspace_id=workspace_id)

    # ------------------------------------------------------------------ helpers

    def _assemble_context(
        self, results: list[RetrievalResult]
    ) -> tuple[str, list[RetrievalResult]]:
        blocks: list[str] = []
        used: list[RetrievalResult] = []
        total = 0
        for r in results:
            block = f"[chunk_id={r.chunk.chunk_id} | page={r.chunk.page_number}]\n{r.chunk.text}"
            if used and total + len(block) > self._s.max_context_chars:
                break
            blocks.append(block)
            used.append(r)
            total += len(block)
        return "\n\n---\n\n".join(blocks), used

    def _confidence(self, grounded: GroundednessReport, cited: list[RetrievalResult]) -> float:
        """Heuristic (not a calibrated probability): 60% groundedness, 40% retrieval strength."""
        top = max(r.score for r in cited)
        span = self._s.retrieval_strong_score - self._s.retrieval_min_score
        retrieval_strength = min(1.0, max(0.0, (top - self._s.retrieval_min_score) / span))
        return round(0.6 * grounded.score + 0.4 * retrieval_strength, 4)

    def _refusal(
        self,
        question: str,
        document_id: str | None,
        reason: str,
        warnings: list[str],
        message: str | None = None,
        provider: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        is_mock: bool | None = None,
    ) -> RAGAnswer:
        gw = self._gateway.provider
        return RAGAnswer(
            answer_id=new_id("ans"),
            document_id=document_id,
            question=question,
            answer=message or "I can't provide an answer to this request.",
            citations=[],
            confidence=0.0,
            requires_review=False,
            refused=True,
            refusal_reason=reason,
            warnings=list(warnings),
            provider=provider or gw.provider_name,
            model_name=model_name or gw.model_name,
            prompt_version=prompt_version or self._gateway.prompts.get(PROMPT_NAME).version,
            embedding_model=self._embedding_model,
            is_mock=gw.is_mock if is_mock is None else is_mock,
        )

    def _insufficient(
        self,
        question: str,
        document_id: str | None,
        retrieval: RetrievalOutcome,
        warnings: list[str],
        actor: str,
        workspace_id: str | None,
        base: dict[str, Any] | None = None,
    ) -> RAGAnswer:
        answer = self._refusal(
            question,
            document_id,
            "insufficient evidence",
            warnings,
            message=INSUFFICIENT_EVIDENCE_ANSWER,
            **(base or {}),
        )
        answer.retrieval_scores = retrieval.candidate_scores
        reasons = (
            [ReviewReason.INSUFFICIENT_EVIDENCE] if self._s.review_on_insufficient_evidence else []
        )
        return self._finalize(answer, actor, reasons=reasons, workspace_id=workspace_id)

    def _finalize(
        self,
        answer: RAGAnswer,
        actor: str,
        reasons: list[ReviewReason],
        original: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> RAGAnswer:
        answer.workspace_id = workspace_id or DEFAULT_WORKSPACE
        if reasons:
            case = self._reviews.create_case(
                target_type=ReviewTargetType.ANSWER,
                target_id=answer.answer_id,
                reasons=reasons,
                original_output={
                    "question": answer.question,
                    "answer": answer.model_dump(mode="json"),
                    **({"model_output": original} if original else {}),
                },
                model_version=answer.model_name,
                prompt_version=answer.prompt_version,
                document_id=answer.document_id,
                workspace_id=answer.workspace_id,
            )
            answer.review_id = case.review_id
            answer.requires_review = True
        self._answers.save(answer)
        outcome = (
            "refused" if answer.refused else ("review" if answer.requires_review else "answered")
        )
        self._metrics.increment("answers_total", labels={"outcome": outcome})
        if answer.groundedness is not None:
            self._metrics.observe("answer_groundedness", answer.groundedness.score)
        if not answer.refused:
            self._metrics.observe("answer_confidence", answer.confidence)
        self._audit.record(
            "answer.generated",
            actor=actor,
            document_id=answer.document_id,
            details={
                "answer_id": answer.answer_id,
                "question_sha256": sha256_text(answer.question),
                "outcome": outcome,
                "refusal_reason": answer.refusal_reason,
                "confidence": answer.confidence,
                "groundedness": answer.groundedness.score if answer.groundedness else None,
                "citations": [c.chunk_id for c in answer.citations],
                "review_id": answer.review_id,
                "model": answer.model_name,
                "prompt_version": answer.prompt_version,
            },
        )
        log_event(
            logger,
            "answer_generated",
            answer_id=answer.answer_id,
            outcome=outcome,
            confidence=answer.confidence,
            retrieval_top_k=len(answer.retrieval_scores),
            retrieval_scores=answer.retrieval_scores,
            embedding_model=answer.embedding_model,
            review_required=answer.requires_review,
            model_provider=answer.provider,
            model_name=answer.model_name,
            prompt_version=answer.prompt_version,
            question_chars=len(answer.question),
        )
        return answer
