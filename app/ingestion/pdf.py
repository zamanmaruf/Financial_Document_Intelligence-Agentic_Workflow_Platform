"""Native PDF inspection and text extraction with pypdf."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.errors import InvalidDocumentError
from app.domain.enums import TextExtractionMethod
from app.domain.models import ExtractedText, PageText

logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass(frozen=True)
class PdfInspection:
    page_count: int
    has_text_layer: bool
    has_images: bool
    producer: str | None
    title: str | None
    # JavaScript / Launch actions / embedded files: never executed or opened, only flagged.
    # Heuristic byte scan: markers inside compressed object streams are not seen.
    has_active_content: bool


_ACTIVE_CONTENT_MARKERS = (b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile")


def open_pdf(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            # Owner-password-only PDFs open with an empty user password; others are rejected.
            try:
                if not reader.decrypt(""):
                    raise InvalidDocumentError("encrypted PDFs are not supported")
            except (PdfReadError, NotImplementedError) as exc:
                raise InvalidDocumentError("encrypted PDFs are not supported") from exc
        _ = len(reader.pages)
        return reader
    except InvalidDocumentError:
        raise
    except Exception as exc:  # pypdf raises a variety of errors for corrupt files
        raise InvalidDocumentError(f"malformed PDF: {type(exc).__name__}") from exc


def inspect_pdf(data: bytes) -> PdfInspection:
    reader = open_pdf(data)
    try:
        page_count = len(reader.pages)
        text_chars = 0
        has_images = False
        for page in reader.pages:
            text_chars += len((page.extract_text() or "").strip())
            resources = page.get("/Resources")
            xobjects = resources.get("/XObject") if resources else None
            if xobjects:
                has_images = True
        meta = reader.metadata
        raw = data[:2_000_000]
        active = any(marker in raw for marker in _ACTIVE_CONTENT_MARKERS)
        return PdfInspection(
            page_count=page_count,
            has_text_layer=text_chars > 0,
            has_images=has_images,
            producer=str(meta.producer) if meta and meta.producer else None,
            title=str(meta.title) if meta and meta.title else None,
            has_active_content=active,
        )
    except InvalidDocumentError:
        raise
    except Exception as exc:
        raise InvalidDocumentError(f"malformed PDF: {type(exc).__name__}") from exc


class PypdfTextExtractor:
    """``DocumentTextExtractor`` for PDFs with an embedded text layer."""

    name = "pypdf"
    method = TextExtractionMethod.NATIVE_PDF

    def is_available(self) -> bool:
        return True

    def extract(self, data: bytes) -> ExtractedText:
        reader = open_pdf(data)
        pages: list[PageText] = []
        warnings: list[str] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except Exception:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                    warnings.append(f"page {i}: text extraction failed")
            lines = [ln.rstrip() for ln in text.splitlines()]
            pages.append(PageText(page_number=i, text="\n".join(ln for ln in lines if ln.strip())))
        return ExtractedText(pages=pages, method=self.method, warnings=warnings)
