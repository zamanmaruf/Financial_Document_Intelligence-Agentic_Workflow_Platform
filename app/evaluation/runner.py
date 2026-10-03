"""End-to-end evaluation runner.

Builds an *isolated* container (temporary data directory, in-memory vector store) using the
configured model/embedding providers, pushes the labelled synthetic dataset through the real
workflow and RAG services, and computes deterministic metrics for:

  classification, extraction, retrieval, answers, workflow routing (HITL)

An optional LLM-as-judge groundedness score is added when ``eval_use_llm_judge`` is enabled; it
is reported alongside, never instead of, the deterministic metrics.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.clock import new_id
from app.core.config import Settings, VectorStoreName
from app.core.errors import DocIntelError
from app.core.text import contains_normalized
from app.domain.enums import DocumentType
from app.domain.models import EvaluationResult, RAGAnswer
from app.evaluation.gate import evaluate_gate, load_baseline, load_thresholds
from app.evaluation.metrics import (
    answer_completeness,
    classification_metrics,
    extraction_metrics,
    fact_present,
    lexical_answer_relevance,
    lexical_context_relevance,
    mean,
    retrieval_query_metrics,
    values_normalized_match,
)
from app.services.container import Container, build_container

logger = logging.getLogger(__name__)

MAX_FAILURE_EXAMPLES = 25


class JudgeLLMOutput(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    verdict: str
    rationale: str = ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class EvaluationRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _isolated_settings(self, data_dir: Path) -> Settings:
        return self._settings.model_copy(
            update={
                "data_dir": data_dir,
                "database_url": None,
                "vector_store": VectorStoreName.MEMORY,
            }
        )

    def run(self, inspect: Callable[[Container], None] | None = None) -> EvaluationResult:
        """Run the suite; ``inspect`` sees the sandbox container before teardown."""
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="docintel-eval-") as tmp:
            container = build_container(self._isolated_settings(Path(tmp)))
            try:
                metrics, failures = self._run(container)
                if inspect is not None:
                    inspect(container)
            finally:
                container.close()
        thresholds = load_thresholds(self._settings.evals_dir / "thresholds.yaml")
        baseline = load_baseline(self._settings.evals_dir / "baseline.json")
        gate = evaluate_gate(metrics, thresholds, baseline)
        metrics["failures"] = failures
        return EvaluationResult(
            run_id=new_id("eval"),
            config={
                **self._settings.public_summary(),
                "llm_model": container.llm.model_name,
                "embedding_model": container.embedder.model_name,
                "prompts": container.prompts.active_versions(),
                "llm_judge": self._settings.eval_use_llm_judge,
            },
            metrics=metrics,
            gate_passed=gate.passed,
            gate_failures=gate.failures,
            duration_s=round(time.perf_counter() - started, 3),
            is_mock=container.llm.is_mock,
        )

    # ------------------------------------------------------------------ internals

    def _run(self, c: Container) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        manifest = json.loads((self._settings.sample_data_dir / "ground_truth.json").read_text())
        pdf_dir = self._settings.sample_data_dir / "pdfs"
        doc_ids: dict[str, str] = {}
        failures: dict[str, list[Any]] = {
            "classification": [],
            "extraction": [],
            "retrieval": [],
            "answers": [],
            "workflow": [],
        }

        y_true: list[str] = []
        y_pred: list[str] = []
        field_items: list[dict[str, Any]] = []
        routing_ok: list[bool] = []
        review_expected: list[bool] = []
        review_actual: list[bool] = []

        for entry in manifest["documents"]:
            if entry["kind"] == "scanned" and not c.text_extraction.ocr_available:
                expected_outcome = "NEEDS_REVIEW"  # routed as ocr_unavailable
            else:
                expected_outcome = entry["expected_outcome"]
            data = (pdf_dir / entry["file"]).read_bytes()
            try:
                upload = c.ingestion.upload(entry["file"], "application/pdf", data)
            except DocIntelError:
                actual = "UPLOAD_REJECTED"
            else:
                doc_id = upload.document.document_id
                doc_ids[entry["file"]] = doc_id
                actual = c.workflow.process(doc_id).status.value
            routing_ok.append(actual == expected_outcome)
            review_expected.append(expected_outcome == "NEEDS_REVIEW")
            review_actual.append(actual == "NEEDS_REVIEW")
            if actual != expected_outcome:
                failures["workflow"].append(
                    {"file": entry["file"], "expected": expected_outcome, "actual": actual}
                )

            if not entry["include_in_eval"] or entry["file"] not in doc_ids:
                continue
            doc = c.documents.get(doc_ids[entry["file"]])
            predicted_type = doc.document_type.value if doc.document_type else "unknown"
            y_true.append(entry["document_type"])
            y_pred.append(predicted_type)
            if predicted_type != entry["document_type"]:
                failures["classification"].append(
                    {
                        "file": entry["file"],
                        "expected": entry["document_type"],
                        "predicted": predicted_type,
                    }
                )
            if entry["document_type"] == DocumentType.UNKNOWN.value:
                continue
            extraction = c.extractions.latest_for_document(doc.document_id)
            for field, expected in entry["expected_fields"].items():
                ent = (
                    extraction.entity(field)
                    if extraction and extraction.document_type.value == entry["document_type"]
                    else None
                )
                item = {
                    "file": entry["file"],
                    "document_type": entry["document_type"],
                    "field": field,
                    "expected": expected,
                    "predicted": ent.value if ent else None,
                    "validation_status": ent.validation_status.value if ent else None,
                }
                field_items.append(item)

        failures["extraction"] = [
            i for i in field_items if not values_normalized_match(i["expected"], i["predicted"])
        ]

        tp = sum(1 for e, a in zip(review_expected, review_actual, strict=True) if e and a)
        fp = sum(1 for e, a in zip(review_expected, review_actual, strict=True) if a and not e)
        fn = sum(1 for e, a in zip(review_expected, review_actual, strict=True) if e and not a)
        workflow = {
            "n_documents": len(routing_ok),
            "routing_accuracy": mean([1.0 if ok else 0.0 for ok in routing_ok]),
            "review_precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "review_recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            "ocr_available": c.text_extraction.ocr_available,
        }

        metrics: dict[str, dict[str, Any]] = {
            "classification": classification_metrics(
                y_true, y_pred, [t.value for t in DocumentType]
            ),
            "extraction": extraction_metrics(field_items),
            "retrieval": self._retrieval(c, doc_ids, failures["retrieval"]),
            "answers": self._answers(c, doc_ids, failures["answers"]),
            "workflow": workflow,
        }
        return metrics, {k: v[:MAX_FAILURE_EXAMPLES] for k, v in failures.items()}

    def _retrieval(
        self, c: Container, doc_ids: dict[str, str], failures: list[Any]
    ) -> dict[str, Any]:
        queries = _read_jsonl(self._settings.evals_dir / "datasets" / "retrieval.jsonl")
        k = self._settings.retrieval_top_k
        per_query: list[dict[str, float]] = []
        doc_hits: list[float] = []
        relevances: list[float] = []
        for q in queries:
            target = doc_ids.get(q["target_file"])
            if target is None:
                continue
            text = c.texts.get(target)
            doc_type = c.documents.get(target).document_type
            all_chunks = c.chunker.chunk(target, text, doc_type) if text else []

            def is_relevant(
                chunk_text: str,
                doc_id: str,
                evidence: list[str] = q["evidence"],
                target_id: str = target,
            ) -> bool:
                return doc_id == target_id and any(
                    contains_normalized(chunk_text, e) for e in evidence
                )

            total_relevant = sum(is_relevant(ch.text, ch.document_id) for ch in all_chunks)
            # min_score=-1: rank quality is measured independently of the answer threshold
            outcome = c.retriever.retrieve(q["query"], top_k=k, min_score=-1.0)
            flags = [is_relevant(r.chunk.text, r.chunk.document_id) for r in outcome.results]
            m = retrieval_query_metrics(flags, total_relevant, k)
            per_query.append(m)
            doc_hits.append(
                1.0 if any(r.chunk.document_id == target for r in outcome.results) else 0.0
            )
            relevances.append(
                lexical_context_relevance(q["query"], [r.chunk.text for r in outcome.results])
            )
            if not m["hit"]:
                failures.append(
                    {"id": q["id"], "query": q["query"], "top_scores": outcome.candidate_scores[:k]}
                )
        return {
            "n_queries": len(per_query),
            "k": k,
            "precision_at_k": mean([m["precision_at_k"] for m in per_query]),
            "recall_at_k": mean([m["recall_at_k"] for m in per_query]),
            "hit_rate": mean([m["hit"] for m in per_query]),
            "mrr": mean([m["reciprocal_rank"] for m in per_query]),
            "document_hit_rate": mean(doc_hits),
            "context_relevance_lexical": mean(relevances),
        }

    def _answers(
        self, c: Container, doc_ids: dict[str, str], failures: list[Any]
    ) -> dict[str, Any]:
        cases = _read_jsonl(self._settings.evals_dir / "datasets" / "answers.jsonl")
        completeness: list[float] = []
        groundedness: list[float] = []
        citation_ok: list[float] = []
        relevance: list[float] = []
        unsupported = total_sentences = 0
        schema_valid: list[float] = []
        correct_refusals: list[float] = []
        false_refusals: list[float] = []
        judge_scores: list[float] = []
        for case in cases:
            doc_id = doc_ids.get(case["target_file"]) if case["target_file"] else None
            scope_doc = doc_id if case["scope"] == "document" else None
            try:
                answer = c.rag.ask(case["question"], document_id=scope_doc)
            except DocIntelError as exc:
                failures.append({"id": case["id"], "error": exc.error_type})
                schema_valid.append(0.0)
                continue
            schema_valid.append(self._schema_valid(answer))
            if not case["answerable"]:
                correct_refusals.append(1.0 if answer.refused else 0.0)
                if not answer.refused:
                    failures.append(
                        {
                            "id": case["id"],
                            "issue": "answered_unanswerable",
                            "answer": answer.answer,
                        }
                    )
                continue
            false_refusals.append(1.0 if answer.refused else 0.0)
            if answer.refused:
                completeness.append(0.0)
                failures.append(
                    {"id": case["id"], "issue": "refused", "reason": answer.refusal_reason}
                )
                continue
            comp = answer_completeness(case["expected_facts"], answer.answer)
            completeness.append(comp)
            relevance.append(lexical_answer_relevance(case["question"], answer.answer))
            if answer.groundedness:
                groundedness.append(answer.groundedness.score)
                unsupported += len(answer.groundedness.unsupported_sentences)
                total_sentences += answer.groundedness.total_sentences
                if answer.groundedness.unsupported_sentences:
                    failures.append(
                        {
                            "id": case["id"],
                            "issue": "unsupported_sentences",
                            "groundedness": answer.groundedness.score,
                            "sentences": answer.groundedness.unsupported_sentences,
                        }
                    )
            cited_ok = [
                1.0
                if cit.document_id == doc_id
                and any(
                    fact_present(f, self._chunk_text(c, cit.document_id, cit.chunk_id))
                    for f in case["expected_facts"]
                )
                else 0.0
                for cit in answer.citations
            ]
            citation_ok.append(mean(cited_ok) if cited_ok else 0.0)
            if comp < 1.0:
                failures.append(
                    {
                        "id": case["id"],
                        "issue": "incomplete",
                        "answer": answer.answer,
                        "expected": case["expected_facts"],
                    }
                )
            if self._settings.eval_use_llm_judge:
                judge_scores.append(self._judge(c, answer))

        result: dict[str, Any] = {
            "n_cases": len(cases),
            "completeness": mean(completeness),
            "groundedness": mean(groundedness),
            "citation_correctness": mean(citation_ok),
            "answer_relevance_lexical": mean(relevance),
            "unsupported_statement_rate": round(unsupported / total_sentences, 4)
            if total_sentences
            else 0.0,
            "schema_validity": mean(schema_valid),
            "correct_refusal_rate": mean(correct_refusals),
            "false_refusal_rate": mean(false_refusals),
        }
        if judge_scores:
            result["llm_judge_groundedness"] = mean(judge_scores)
        return result

    @staticmethod
    def _chunk_text(c: Container, document_id: str, chunk_id: str) -> str:
        text = c.texts.get(document_id)
        if text is None:
            return ""
        doc = c.documents.get(document_id)
        for ch in c.chunker.chunk(document_id, text, doc.document_type):
            if ch.chunk_id == chunk_id:
                return ch.text
        return ""

    @staticmethod
    def _schema_valid(answer: RAGAnswer) -> float:
        try:
            RAGAnswer.model_validate_json(answer.model_dump_json())
        except ValidationError:
            return 0.0
        return 1.0

    @staticmethod
    def _judge(c: Container, answer: RAGAnswer) -> float:
        context = "\n\n".join(cit.text_snippet for cit in answer.citations)
        try:
            res = c.gateway.invoke(
                "validation.groundedness_judge",
                render_vars={"answer": answer.answer, "context": context},
                schema=JudgeLLMOutput,
                operation="judge",
            )
        except DocIntelError:
            return 0.0
        return res.output.score
