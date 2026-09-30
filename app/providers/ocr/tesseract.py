"""Local OCR with Tesseract (pages rendered with pdfium). Requires the ``tesseract`` binary."""

from __future__ import annotations

import shutil

from app.domain.enums import TextExtractionMethod
from app.domain.models import ExtractedText, PageText


class TesseractOCRExtractor:
    name = "tesseract"
    method = TextExtractionMethod.OCR_TESSERACT

    def __init__(self, dpi: int = 300, lang: str = "eng") -> None:
        self._scale = dpi / 72.0
        self._lang = lang

    def is_available(self) -> bool:
        return shutil.which("tesseract") is not None

    def extract(self, data: bytes) -> ExtractedText:
        import pypdfium2 as pdfium
        import pytesseract

        pdf = pdfium.PdfDocument(data)
        pages: list[PageText] = []
        try:
            for i in range(len(pdf)):
                image = pdf[i].render(scale=self._scale).to_pil()
                # --psm 6: assume a uniform block of text; preserves line structure of tables
                text = pytesseract.image_to_string(image, lang=self._lang, config="--psm 6")
                lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
                pages.append(PageText(page_number=i + 1, text="\n".join(lines)))
        finally:
            pdf.close()
        return ExtractedText(pages=pages, method=self.method)
