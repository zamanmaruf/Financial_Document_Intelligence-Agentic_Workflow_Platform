"""Typed error hierarchy.

Errors carry a stable ``error_type`` used in logs, metrics and API responses so that failure
modes can be counted and alerted on without parsing messages.
"""

from __future__ import annotations


class DocIntelError(Exception):
    error_type = "docintel_error"
    http_status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DocIntelError):
    error_type = "not_found"
    http_status = 404


class DocumentNotFoundError(NotFoundError):
    error_type = "document_not_found"


class ReviewNotFoundError(NotFoundError):
    error_type = "review_not_found"


class InvalidDocumentError(DocIntelError):
    """Upload rejected: wrong type, too large, malformed, encrypted..."""

    error_type = "invalid_document"
    http_status = 422


class EmptyDocumentError(DocIntelError):
    error_type = "empty_document"
    http_status = 422


class OCRUnavailableError(DocIntelError):
    error_type = "ocr_unavailable"
    http_status = 503


class ProviderError(DocIntelError):
    """A model / embedding / OCR provider call failed."""

    error_type = "provider_error"
    http_status = 502
    retries_exhausted = False


class ProviderTimeoutError(ProviderError):
    error_type = "provider_timeout"
    http_status = 504


class ProviderResponseError(ProviderError):
    """The provider answered, but the output could not be parsed or validated."""

    error_type = "provider_response_invalid"


class ProviderConfigurationError(DocIntelError):
    error_type = "provider_misconfigured"
    http_status = 500


class VectorStoreError(DocIntelError):
    error_type = "vector_store_error"
    http_status = 503


class IllegalTransitionError(DocIntelError):
    error_type = "illegal_workflow_transition"
    http_status = 409


class InvalidStateError(DocIntelError):
    error_type = "invalid_state"
    http_status = 409


class GuardrailViolationError(DocIntelError):
    error_type = "guardrail_violation"
    http_status = 400


class AuthorizationError(DocIntelError):
    error_type = "forbidden"
    http_status = 403


class AuthenticationError(DocIntelError):
    error_type = "unauthenticated"
    http_status = 401


class RateLimitedError(DocIntelError):
    error_type = "rate_limited"
    http_status = 429

    def __init__(self, message: str, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s
