from __future__ import annotations

from enum import StrEnum


class DocumentType(StrEnum):
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    FUND_SUMMARY = "fund_summary"
    UNKNOWN = "unknown"

    @classmethod
    def supported(cls) -> list[DocumentType]:
        return [t for t in cls if t is not cls.UNKNOWN]


class WorkflowStatus(StrEnum):
    INGESTED = "INGESTED"
    TEXT_EXTRACTED = "TEXT_EXTRACTED"
    CLASSIFIED = "CLASSIFIED"
    ENTITIES_EXTRACTED = "ENTITIES_EXTRACTED"
    VALIDATED = "VALIDATED"
    INDEXED = "INDEXED"
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"
    UNVERIFIED = "unverified"  # value present but evidence could not be located in source
    CONFLICT = "conflict"
    CORRECTED = "corrected"  # overridden by a human reviewer


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"
    SUPERSEDED = "superseded"  # document was reprocessed before the review was resolved


class ReviewTargetType(StrEnum):
    DOCUMENT_PROCESSING = "document_processing"
    ANSWER = "answer"


class ReviewReason(StrEnum):
    LOW_CLASSIFICATION_CONFIDENCE = "low_classification_confidence"
    UNKNOWN_DOCUMENT_TYPE = "unknown_document_type"
    LOW_EXTRACTION_CONFIDENCE = "low_extraction_confidence"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    VALIDATION_RULE_FAILED = "validation_rule_failed"
    CONFLICTING_VALUES = "conflicting_values"
    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    UNVERIFIED_EVIDENCE = "unverified_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    WEAK_GROUNDING = "weak_grounding"
    LOW_ANSWER_CONFIDENCE = "low_answer_confidence"
    GUARDRAIL_TRIGGERED = "guardrail_triggered"
    RETRIES_EXHAUSTED = "retries_exhausted"
    OCR_UNAVAILABLE = "ocr_unavailable"
    OCR_USED = "ocr_used"


class TextExtractionMethod(StrEnum):
    NATIVE_PDF = "native_pdf"
    OCR_TESSERACT = "ocr_tesseract"
    OCR_TEXTRACT = "ocr_textract"
    OCR_VISION_LLM = "ocr_vision_llm"
    NONE = "none"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
