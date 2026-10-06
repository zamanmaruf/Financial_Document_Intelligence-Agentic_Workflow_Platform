"""Training records for extraction fine-tuning, built from the production prompt.

A record is the exact system and user message the extraction service sends (rendered through the
``PromptRegistry`` at a pinned prompt version) plus the JSON answer the service expects back:
every field with its value, the value as printed, the verbatim evidence line, the page and a
confidence. ``check_target`` replays the answer through the real ``EntityExtractor`` so a record
is only kept if production code would accept it and recover the expected values.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.text import normalize_ws
from app.domain.enums import DocumentType, TextExtractionMethod
from app.domain.models import ExtractedText, ModelInvocation, PageText
from app.evaluation.metrics import values_normalized_match
from app.extraction.schemas import FieldKind, field_specs
from app.extraction.service import (
    PROMPT_NAME,
    EntityExtractor,
    ExtractionLLMOutput,
    field_spec_text,
    pages_text,
)
from app.finetune.corpus import FieldTruth, SyntheticDoc
from app.observability.cost import CostEstimator
from app.observability.metrics import InMemoryMetrics
from app.prompts.registry import PromptRegistry
from app.providers.llm.base import LLMRequest, LLMResponse
from app.services.model_gateway import ModelGateway

PRESENT_CONFIDENCE = 0.95


def extracted_text(pages: list[str]) -> ExtractedText:
    return ExtractedText(
        pages=[PageText(page_number=i, text=t) for i, t in enumerate(pages, start=1)],
        method=TextExtractionMethod.NATIVE_PDF,
    )


def evidence_line(text: ExtractedText, truth: FieldTruth) -> str:
    """The line as the model sees it (after PDF text extraction) that carries the value."""
    if truth.line is None or truth.page is None:
        raise ValueError("field has no printed line")
    target = normalize_ws(truth.line)
    lines = [ln.strip() for ln in text.pages[truth.page - 1].text.splitlines()]
    for ln in lines:
        if normalize_ws(ln) == target:
            return ln
    for ln in lines:
        if target in normalize_ws(ln):
            return ln
    raise ValueError(f"line {truth.line!r} not found on page {truth.page} after extraction")


def _json_value(value: float | str) -> float | int | str:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def target_output(doc: SyntheticDoc, text: ExtractedText) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for spec in field_specs(doc.document_type):
        truth = doc.fields.get(spec.name)
        if truth is None or truth.value is None:
            fields[spec.name] = {"value": None, "confidence": 0}
            continue
        fields[spec.name] = {
            "value": _json_value(truth.value),
            "raw_text": truth.raw_text,
            "evidence_snippet": evidence_line(text, truth),
            "page_number": truth.page,
            "confidence": PRESENT_CONFIDENCE,
            "alternatives": [],
        }
    return {"fields": fields}


def prompt_messages(
    registry: PromptRegistry,
    prompt_version: str,
    document_type: DocumentType,
    text: ExtractedText,
) -> tuple[str, str]:
    spec = registry.get(PROMPT_NAME, prompt_version)
    return spec.render(
        document_type=document_type.value,
        field_spec=field_spec_text(field_specs(document_type)),
        document_pages=pages_text(text),
    )


def training_record(
    registry: PromptRegistry,
    prompt_version: str,
    document_type: DocumentType,
    text: ExtractedText,
    target: dict[str, Any],
) -> dict[str, Any]:
    system, user = prompt_messages(registry, prompt_version, document_type, text)
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {
                "role": "assistant",
                "content": json.dumps(target, ensure_ascii=False, separators=(",", ":")),
            },
        ]
    }


class _FixedAnswer:
    """An ``LLMProvider`` that always returns one prepared answer."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def provider_name(self) -> str:
        return "fixed"

    @property
    def model_name(self) -> str:
        return "training-target"

    @property
    def is_mock(self) -> bool:
        return True

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text=self._text, provider="fixed", model_name="training-target")


class _Discard:
    def save(self, inv: ModelInvocation) -> None:
        return None


def check_target(
    registry: PromptRegistry,
    prompt_version: str,
    document_type: DocumentType,
    text: ExtractedText,
    answer: str,
    expected: dict[str, float | str | None],
) -> list[str]:
    """Problems found when production extraction consumes ``answer`` (empty means valid)."""
    ExtractionLLMOutput.model_validate_json(answer)
    gateway = ModelGateway(
        provider=_FixedAnswer(answer),
        prompts=PromptRegistry([registry.get(PROMPT_NAME, prompt_version)]),
        invocations=_Discard(),
        metrics=InMemoryMetrics(),
        cost=CostEstimator({}),
        json_repair_attempts=0,
    )
    extractor = EntityExtractor(gateway, min_confidence=0.6, tolerance_ratio=0.005)
    outcome = extractor.extract(document_type, text, document_id="finetune-check")
    if outcome is None:
        return [f"{document_type.value}: no extraction schema"]
    result, _ = outcome
    kinds = {s.name: s.kind for s in field_specs(document_type)}
    problems: list[str] = []
    for name, want in expected.items():
        entity = result.entity(name)
        got = entity.value if entity else None
        if not values_normalized_match(want, got):
            problems.append(f"{name}: expected {want!r}, extracted {got!r}")
        if want is not None and entity is not None:
            if entity.evidence is None or not entity.evidence.verified:
                problems.append(f"{name}: evidence not verified")
            if kinds[name] == FieldKind.AMOUNT and not isinstance(entity.value, float):
                problems.append(f"{name}: amount is not numeric")
    return problems
