"""Score one extraction model on the held-out fine-tuning test set or the original samples.

The document type is given (classification is not part of this comparison) and the real
``EntityExtractor`` runs through a ``ModelGateway``, so validation, evidence checks, retries and
the JSON repair prompt all behave as in production. A recording wrapper around the provider
counts how often the first reply was already valid JSON in the right shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import ValidationError

from app.core.errors import DocIntelError
from app.domain.enums import DocumentType
from app.domain.models import ExtractedText, ModelInvocation
from app.evaluation.metrics import extraction_metrics, values_normalized_match
from app.extraction.service import EntityExtractor, ExtractionLLMOutput
from app.finetune.records import extracted_text
from app.ingestion.pdf import PypdfTextExtractor
from app.observability.metrics import percentile
from app.providers.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.services.model_gateway import extract_json_object


@dataclass
class EvalDoc:
    doc_id: str
    document_type: DocumentType
    text: ExtractedText
    expected: dict[str, Any]
    traits: list[str] = field(default_factory=list)


def heldout_docs(data_dir: Path, split: str = "test") -> list[EvalDoc]:
    rows = [json.loads(line) for line in (data_dir / "documents.jsonl").read_text().splitlines()]
    return [
        EvalDoc(
            doc_id=r["doc_id"],
            document_type=DocumentType(r["document_type"]),
            text=extracted_text(r["pages"]),
            expected=r["expected"],
            traits=r["traits"],
        )
        for r in rows
        if r["split"] == split
    ]


def sample_docs(sample_dir: Path) -> list[EvalDoc]:
    """The labelled ``sample_data`` PDFs that the main evaluation scores (text documents only)."""
    manifest = json.loads((sample_dir / "ground_truth.json").read_text())
    reader = PypdfTextExtractor()
    docs: list[EvalDoc] = []
    for entry in manifest["documents"]:
        if not entry["include_in_eval"] or entry["document_type"] == DocumentType.UNKNOWN.value:
            continue
        docs.append(
            EvalDoc(
                doc_id=entry["file"],
                document_type=DocumentType(entry["document_type"]),
                text=reader.extract((sample_dir / "pdfs" / entry["file"]).read_bytes()),
                expected=entry["expected_fields"],
                traits=[entry["edge_case"]] if entry["edge_case"] else [],
            )
        )
    return docs


class RecordingProvider:
    """Wraps a provider and keeps the raw text of every reply since the last ``reset``."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.replies: list[str] = []

    @property
    def provider_name(self) -> str:
        return self.inner.provider_name

    @property
    def model_name(self) -> str:
        return self.inner.model_name

    @property
    def is_mock(self) -> bool:
        return self.inner.is_mock

    def generate(self, request: LLMRequest) -> LLMResponse:
        response = self.inner.generate(request)
        self.replies.append(response.text)
        return response

    def reset(self) -> None:
        self.replies = []


class InvocationList:
    def __init__(self) -> None:
        self.items: list[ModelInvocation] = []

    def save(self, inv: ModelInvocation) -> None:
        self.items.append(inv)


def _valid_reply(text: str) -> bool:
    try:
        ExtractionLLMOutput.model_validate(extract_json_object(text))
    except (ValueError, ValidationError):
        return False
    return True


def evaluate_extraction(
    docs: list[EvalDoc],
    extractor: EntityExtractor,
    recorder: RecordingProvider,
    invocations: InvocationList,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    first_valid: list[float] = []
    repaired = failed = 0
    latencies: list[float] = []
    costs: list[float | None] = []
    input_tokens: list[int] = []
    output_tokens: list[int] = []
    mismatches: list[dict[str, Any]] = []
    trait_items: dict[str, list[bool]] = {}
    for doc in docs:
        recorder.reset()
        before = len(invocations.items)
        try:
            outcome = extractor.extract(doc.document_type, doc.text, document_id=doc.doc_id)
        except DocIntelError as exc:
            failed += 1
            outcome = None
            mismatches.append({"doc_id": doc.doc_id, "error": exc.error_type})
        for inv in invocations.items[before:]:
            latencies.append(inv.latency_ms)
            costs.append(inv.estimated_cost_usd)
            input_tokens.append(inv.input_tokens)
            output_tokens.append(inv.output_tokens)
        if recorder.replies:
            first_valid.append(1.0 if _valid_reply(recorder.replies[0]) else 0.0)
            if len(recorder.replies) > 1 and outcome is not None:
                repaired += 1
        result = outcome[0] if outcome else None
        for name, want in doc.expected.items():
            entity = result.entity(name) if result else None
            got = entity.value if entity else None
            items.append(
                {
                    "file": doc.doc_id,
                    "document_type": doc.document_type.value,
                    "field": name,
                    "expected": want,
                    "predicted": got,
                    "validation_status": entity.validation_status.value if entity else None,
                }
            )
            ok = values_normalized_match(want, got)
            for trait in doc.traits:
                trait_items.setdefault(trait, []).append(ok)
            if not ok and result is not None:
                mismatches.append(
                    {
                        "doc_id": doc.doc_id,
                        "field": name,
                        "expected": want,
                        "predicted": got,
                        "validation_status": entity.validation_status.value if entity else None,
                        "requires_review": result.requires_review,
                    }
                )
    metrics = extraction_metrics(items)
    n = len(docs)
    priced = [c for c in costs if c is not None]
    return {
        "n_documents": n,
        **metrics,
        "field_accuracy_by_trait": {
            t: round(sum(v) / len(v), 4) for t, v in sorted(trait_items.items())
        },
        "json_first_reply_valid_rate": round(mean(first_valid), 4) if first_valid else None,
        "json_repaired_documents": repaired,
        "call_failures": failed,
        "latency_ms_p50": round(percentile(latencies, 0.5), 1) if latencies else None,
        "latency_ms_p95": round(percentile(latencies, 0.95), 1) if latencies else None,
        "input_tokens_mean": round(mean(input_tokens), 1) if input_tokens else None,
        "output_tokens_mean": round(mean(output_tokens), 1) if output_tokens else None,
        "cost_per_document_usd": round(sum(priced) / n, 6)
        if n and len(priced) == len(costs)
        else None,
        "mismatches": mismatches,
    }
