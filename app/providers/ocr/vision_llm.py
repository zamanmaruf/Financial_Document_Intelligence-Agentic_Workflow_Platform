"""Vision OCR: a multimodal chat model reads each rendered page image.

Pages are rendered with pdfium (long edge capped, since vision models downscale or reject large
images) and sent one at a time through the model gateway, so every call is retried, validated,
costed and logged like any other model call. The model is told to copy values verbatim, but a
vision model can still misread or invent a digit without raising an error. When Tesseract is
installed it reads the same image, and pages where the two engines read different numbers get a
warning that ends up in the review case.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

from app.core.text import extract_numbers
from app.domain.enums import TextExtractionMethod
from app.domain.models import ExtractedText, PageText
from app.observability.logging import document_id_var, workflow_id_var
from app.providers.llm.base import ImageInput

if TYPE_CHECKING:
    from PIL import Image

    from app.services.model_gateway import ModelGateway

PROMPT_NAME = "ocr.page_transcription"
MAX_LISTED_NUMBERS = 6


class PageTranscriptionLLMOutput(BaseModel):
    lines: list[str] = Field(default_factory=list)


class PageImageReader(Protocol):
    def read_image(self, image: Image.Image) -> str: ...


def number_disagreement(primary: str, reference: str) -> tuple[list[str], list[str]]:
    """Numbers (canonical form) only ``primary`` read, and numbers only ``reference`` read."""
    a, b = set(extract_numbers(primary)), set(extract_numbers(reference))
    return sorted(a - b, key=_num_key), sorted(b - a, key=_num_key)


def _num_key(n: str) -> tuple[float, str]:
    try:
        return (float(n), n)
    except ValueError:
        return (0.0, n)


class VisionLLMOCRExtractor:
    method = TextExtractionMethod.OCR_VISION_LLM

    def __init__(
        self,
        gateway: ModelGateway,
        max_edge_px: int = 1568,
        cross_check: PageImageReader | None = None,
    ) -> None:
        self._gateway = gateway
        self._max_edge_px = max_edge_px
        self._cross_check = cross_check
        self.name = f"{gateway.provider.provider_name} vision"

    def is_available(self) -> bool:
        return True  # availability is only known at call time (credentials / network)

    def render_pages(self, data: bytes) -> list[Image.Image]:
        import pypdfium2 as pdfium

        from app.documents.pages import PDFIUM_LOCK

        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                images = []
                for i in range(len(pdf)):
                    page = pdf[i]
                    width, height = page.get_size()
                    scale = self._max_edge_px / max(width, height, 1.0)
                    images.append(page.render(scale=scale).to_pil())
                return images
            finally:
                pdf.close()

    def extract(self, data: bytes) -> ExtractedText:
        images = self.render_pages(data)
        pages: list[PageText] = []
        warnings: list[str] = []
        for i, image in enumerate(images):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            result = self._gateway.invoke(
                PROMPT_NAME,
                render_vars={"page_number": i + 1, "page_count": len(images)},
                schema=PageTranscriptionLLMOutput,
                operation="ocr",
                images=[ImageInput.from_bytes(buf.getvalue())],
                document_id=document_id_var.get(),
                workflow_id=workflow_id_var.get(),
            )
            text = "\n".join(ln.rstrip() for ln in result.output.lines if ln.strip())
            pages.append(PageText(page_number=i + 1, text=text))
            if self._cross_check is not None:
                warning = self._compare(i + 1, text, self._cross_check.read_image(image))
                if warning:
                    warnings.append(warning)
        return ExtractedText(pages=pages, method=self.method, warnings=warnings)

    def _compare(self, page_number: int, vision_text: str, tesseract_text: str) -> str | None:
        only_vision, only_tesseract = number_disagreement(vision_text, tesseract_text)
        if not only_vision and not only_tesseract:
            return None

        def listing(values: list[str]) -> str:
            shown = ", ".join(values[:MAX_LISTED_NUMBERS]) or "none"
            extra = len(values) - MAX_LISTED_NUMBERS
            return f"{shown} (+{extra} more)" if extra > 0 else shown

        return (
            f"page {page_number}: {self.name} and Tesseract read different numbers; check them "
            f"against the page. Only the vision model read: {listing(only_vision)}. "
            f"Only Tesseract read: {listing(only_tesseract)}"
        )
