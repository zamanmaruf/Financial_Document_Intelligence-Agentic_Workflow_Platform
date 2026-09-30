"""``DocumentTextExtractor`` interface and the OCR-routing text extraction service."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.core.errors import EmptyDocumentError, OCRUnavailableError, ProviderError
from app.domain.enums import TextExtractionMethod
from app.domain.models import ExtractedText
from app.ingestion.pdf import PypdfTextExtractor, inspect_pdf
from app.observability.logging import log_event

logger = logging.getLogger(__name__)


@runtime_checkable
class DocumentTextExtractor(Protocol):
    name: str
    method: TextExtractionMethod

    def is_available(self) -> bool: ...

    def extract(self, data: bytes) -> ExtractedText: ...


class TextExtractionService:
    """Chooses native extraction or OCR.

    Decision: use the native text layer when it has at least ``min_chars_per_page`` characters
    per page on average; otherwise treat the PDF as scanned and use the OCR engine if one is
    configured and available. Scanned PDFs without an OCR engine raise ``OCRUnavailableError``
    (the workflow routes them to human review). PDFs with neither text nor images raise
    ``EmptyDocumentError``.
    """

    def __init__(
        self,
        native: DocumentTextExtractor | None = None,
        ocr: DocumentTextExtractor | None = None,
        min_chars_per_page: int = 40,
    ) -> None:
        self.native = native or PypdfTextExtractor()
        self.ocr = ocr
        self.min_chars_per_page = min_chars_per_page

    @property
    def ocr_available(self) -> bool:
        return self.ocr is not None and self.ocr.is_available()

    def extract(self, data: bytes) -> ExtractedText:
        native = self.native.extract(data)
        pages = max(1, len(native.pages))
        if native.char_count / pages >= self.min_chars_per_page:
            return native

        inspection = inspect_pdf(data)
        if not inspection.has_images and native.char_count == 0:
            raise EmptyDocumentError("document contains no extractable text or images")

        if not self.ocr_available or self.ocr is None:
            raise OCRUnavailableError(
                "document appears to be scanned (no usable text layer) and no OCR engine is "
                "available"
            )
        log_event(logger, "ocr_fallback", engine=self.ocr.name, native_chars=native.char_count)
        try:
            ocr_text = self.ocr.extract(data)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"OCR failed: {type(exc).__name__}") from exc
        if ocr_text.char_count == 0:
            raise EmptyDocumentError("OCR produced no text")
        ocr_text.warnings.append(
            f"text obtained via OCR ({self.ocr.name}); values may contain recognition errors"
        )
        return ocr_text
