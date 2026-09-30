"""Document classification via the ModelGateway with confidence-based review routing."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import DocumentType
from app.domain.models import ClassificationResult, ModelInvocation
from app.services.model_gateway import ModelGateway

PROMPT_NAME = "classification.document_type"


class ClassificationLLMOutput(BaseModel):
    """Schema the model must return. Unknown labels are mapped to ``unknown``."""

    document_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = Field(max_length=600)

    @field_validator("document_type")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return v.strip().lower().replace(" ", "_").replace("-", "_")


class DocumentClassifier:
    def __init__(self, gateway: ModelGateway, min_confidence: float, max_chars: int) -> None:
        self._gateway = gateway
        self._min_confidence = min_confidence
        self._max_chars = max_chars

    def classify(
        self, text: str, document_id: str | None = None, workflow_id: str | None = None
    ) -> tuple[ClassificationResult, ModelInvocation]:
        excerpt = text[: self._max_chars]
        supported = ", ".join(t.value for t in DocumentType)
        result = self._gateway.invoke(
            PROMPT_NAME,
            render_vars={"supported_types": supported, "document_text": excerpt},
            schema=ClassificationLLMOutput,
            operation="classification",
            document_id=document_id,
            workflow_id=workflow_id,
        )
        out = result.output
        try:
            doc_type = DocumentType(out.document_type)
        except ValueError:
            doc_type = DocumentType.UNKNOWN
        requires_review = doc_type == DocumentType.UNKNOWN or out.confidence < self._min_confidence
        classification = ClassificationResult(
            document_type=doc_type,
            confidence=out.confidence,
            reasoning_summary=out.reasoning_summary,
            requires_review=requires_review,
            provider=result.invocation.provider,
            model_name=result.invocation.model_name,
            prompt_version=result.prompt.version,
            is_mock=result.invocation.is_mock,
        )
        return classification, result.invocation
