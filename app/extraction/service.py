"""Structured entity extraction with typed coercion, evidence verification and masking."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.clock import new_id
from app.core.text import (
    all_numbers,
    canonical_number,
    contains_normalized,
    normalize_number,
    normalize_ws,
    parse_amount,
)
from app.domain.enums import DocumentType, ReviewReason, Severity, ValidationStatus
from app.domain.models import (
    Evidence,
    ExtractedEntity,
    ExtractedText,
    ExtractionResult,
    FieldValue,
    ModelInvocation,
)
from app.extraction.schemas import SCHEMAS, FieldKind, FieldSpec, field_specs
from app.extraction.validation import INJECTED_EVIDENCE_RULE, validate_extraction
from app.guardrails.pii import redact_text
from app.services.model_gateway import ModelGateway

PROMPT_NAME = "extraction.financial_entities"
UNVERIFIED_CONFIDENCE_PENALTY = 0.6


class FieldLLMOutput(BaseModel):
    value: float | str | None = None
    raw_text: str | None = None
    evidence_snippet: str | None = None
    page_number: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    alternatives: list[float | str] = Field(default_factory=list)


class ExtractionLLMOutput(BaseModel):
    fields: dict[str, FieldLLMOutput]


def mask_account_number(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return None
    return f"****{digits[-4:]}"


def same_value(a: FieldValue, b: FieldValue) -> bool:
    """Whether two extracted values denote the same thing (case/spacing variants are not conflicts).

    Numbers must agree to the cent: a genuine conflict can be a small difference.
    """
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 0.005
    if isinstance(a, str) and isinstance(b, str):
        return normalize_ws(a).casefold() == normalize_ws(b).casefold()
    return a == b


def coerce_field_value(kind: FieldKind, value: Any) -> Any:
    """Normalize model output into the schema's value type before Pydantic validation."""
    if value is None:
        return None
    if kind in (FieldKind.AMOUNT, FieldKind.PERCENT) and isinstance(value, str):
        if kind == FieldKind.PERCENT:
            norm = normalize_number(value.replace("%", ""))
            return float(norm) if norm is not None else value
        parsed = parse_amount(value)
        return parsed[0] if parsed else value
    if kind in (FieldKind.AMOUNT, FieldKind.PERCENT) and isinstance(value, int | float):
        return float(value)
    if kind == FieldKind.CURRENCY and isinstance(value, str):
        return value.strip().upper()
    if kind == FieldKind.MASKED_ACCOUNT:
        return mask_account_number(str(value)) or str(value)
    if isinstance(value, str):
        return value.strip()
    return value


def _verify_evidence(
    text: ExtractedText, field: FieldLLMOutput, kind: FieldKind, value: FieldValue
) -> tuple[bool, int | None]:
    snippet = field.evidence_snippet
    if not snippet:
        return False, field.page_number
    candidates = [p for p in text.pages if p.page_number == field.page_number] or text.pages
    for page in candidates:
        if contains_normalized(page.text, snippet):
            if kind in (FieldKind.AMOUNT, FieldKind.PERCENT):
                # the returned value (not just the quoted raw text) must appear in the evidence
                printed = all_numbers(snippet)
                if field.raw_text:
                    raw_norm = normalize_number(field.raw_text.replace("%", ""))
                    if raw_norm is not None and raw_norm.lstrip("-") not in printed:
                        return False, page.page_number
                if isinstance(value, float) and canonical_number(value) not in printed:
                    return False, page.page_number
            return True, page.page_number
    return False, field.page_number


def field_spec_text(specs: list[FieldSpec]) -> str:
    """The ``field_spec`` prompt variable (also used to build fine-tuning records)."""
    return "\n".join(
        f"- {s.name} ({s.kind.value}{', required' if s.required else ''}): {s.description}"
        for s in specs
    )


def pages_text(text: ExtractedText) -> str:
    """The ``document_pages`` prompt variable."""
    return "\n\n".join(f"[page {p.page_number}]\n{p.text}" for p in text.pages)


class EntityExtractor:
    def __init__(
        self, gateway: ModelGateway, min_confidence: float, tolerance_ratio: float
    ) -> None:
        self._gateway = gateway
        self._min_confidence = min_confidence
        self._tolerance = tolerance_ratio

    def extract(
        self,
        document_type: DocumentType,
        text: ExtractedText,
        document_id: str,
        workflow_id: str | None = None,
    ) -> tuple[ExtractionResult, ModelInvocation] | None:
        specs = field_specs(document_type)
        if not specs:
            return None
        result = self._gateway.invoke(
            PROMPT_NAME,
            render_vars={
                "document_type": document_type.value,
                "field_spec": field_spec_text(specs),
                "document_pages": pages_text(text),
            },
            structured_vars={
                "document_type": document_type.value,
                "pages": [p.model_dump() for p in text.pages],
                "fields": [s.model_dump(mode="json") for s in specs],
            },
            schema=ExtractionLLMOutput,
            operation="extraction",
            document_id=document_id,
            workflow_id=workflow_id,
        )
        schema_model = SCHEMAS[document_type]
        entities: list[ExtractedEntity] = []
        schema_failures: list[str] = []
        for spec in specs:
            raw = result.output.fields.get(spec.name) or FieldLLMOutput()
            coerced = coerce_field_value(spec.kind, raw.value)
            messages: list[str] = []
            if spec.kind == FieldKind.MASKED_ACCOUNT and raw.raw_text:
                # Models can garble digits while masking; the printed number, once located in the
                # source text, is authoritative.
                printed = any(contains_normalized(p.text, raw.raw_text) for p in text.pages)
                recomputed = mask_account_number(raw.raw_text) if printed else None
                if recomputed is not None and recomputed != coerced:
                    messages.append(
                        f"masked value recomputed from the printed account number "
                        f"(model returned {coerced!r})"
                    )
                    coerced = recomputed
            value: FieldValue = None
            try:
                validated = schema_model.model_validate({spec.name: coerced})
                value = getattr(validated, spec.name)
            except ValidationError:
                schema_failures.append(spec.name)
                messages.append(f"model value {raw.value!r} failed schema validation")

            verified, page = _verify_evidence(text, raw, spec.kind, value)
            confidence = raw.confidence if value is not None else 0.0
            if value is not None and not verified:
                confidence = round(confidence * UNVERIFIED_CONFIDENCE_PENALTY, 4)

            raw_text = raw.raw_text
            snippet = raw.evidence_snippet
            if spec.kind == FieldKind.MASKED_ACCOUNT:
                raw_text = mask_account_number(raw_text) if raw_text else None
            # never persist full account numbers / emails found in evidence lines
            snippet = redact_text(snippet) if snippet else None

            alternatives: list[FieldValue] = []
            for alt in raw.alternatives:
                alt_c = coerce_field_value(spec.kind, alt)
                if not isinstance(alt_c, float | str):
                    continue
                if not any(same_value(alt_c, seen) for seen in [value, *alternatives]):
                    alternatives.append(alt_c)

            entities.append(
                ExtractedEntity(
                    name=spec.name,
                    value=value,
                    raw_text=raw_text,
                    evidence=Evidence(page_number=page, snippet=snippet, verified=verified)
                    if snippet
                    else None,
                    confidence=confidence,
                    validation_status=ValidationStatus.INVALID
                    if spec.name in schema_failures
                    else ValidationStatus.MISSING,
                    messages=messages,
                    alternatives=alternatives,
                )
            )

        present = [e for e in entities if e.value is not None]
        overall = round(sum(e.confidence for e in present) / len(present), 4) if present else 0.0
        extraction = ExtractionResult(
            extraction_id=new_id("ext"),
            document_id=document_id,
            document_type=document_type,
            entities=entities,
            overall_confidence=overall,
            provider=result.invocation.provider,
            model_name=result.invocation.model_name,
            prompt_version=result.prompt.version,
            is_mock=result.invocation.is_mock,
        )
        issues = validate_extraction(extraction, self._tolerance)
        for name in schema_failures:
            ent = extraction.entity(name)
            if ent is not None:
                ent.validation_status = ValidationStatus.INVALID
        extraction.validation_issues = issues
        extraction.review_reasons = self._review_reasons(extraction, schema_failures, specs)
        extraction.requires_review = bool(extraction.review_reasons)
        return extraction, result.invocation

    def _review_reasons(
        self, extraction: ExtractionResult, schema_failures: list[str], specs: list[FieldSpec]
    ) -> list[ReviewReason]:
        reasons: list[ReviewReason] = []
        required = {s.name for s in specs if s.required}
        low_conf = extraction.overall_confidence < self._min_confidence or any(
            e.value is not None and e.name in required and e.confidence < self._min_confidence
            for e in extraction.entities
        )
        if low_conf:
            reasons.append(ReviewReason.LOW_EXTRACTION_CONFIDENCE)
        rules = {i.rule for i in extraction.validation_issues}
        if schema_failures or "field_format" in rules:
            reasons.append(ReviewReason.SCHEMA_VALIDATION_FAILED)
        if "conflicting_values" in rules:
            reasons.append(ReviewReason.CONFLICTING_VALUES)
        if "required_field" in rules:
            reasons.append(ReviewReason.MISSING_REQUIRED_FIELDS)
        if "evidence_not_found" in rules:
            reasons.append(ReviewReason.UNVERIFIED_EVIDENCE)
        if INJECTED_EVIDENCE_RULE in rules:
            reasons.append(ReviewReason.GUARDRAIL_TRIGGERED)
        cross_field_errors = [
            i
            for i in extraction.validation_issues
            if i.severity == Severity.ERROR
            and i.rule
            not in {"required_field", "field_format", "conflicting_values", INJECTED_EVIDENCE_RULE}
        ]
        if cross_field_errors:
            reasons.append(ReviewReason.VALIDATION_RULE_FAILED)
        return reasons
