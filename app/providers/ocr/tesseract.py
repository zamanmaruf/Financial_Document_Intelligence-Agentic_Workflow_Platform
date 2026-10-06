"""Local OCR with Tesseract (pages rendered with pdfium). Requires the ``tesseract`` binary."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from app.domain.enums import TextExtractionMethod
from app.domain.models import ExtractedText, PageText

if TYPE_CHECKING:
    from PIL import Image

    from app.documents.pages import OcrWord


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

    def words(self, image: Image.Image) -> list[OcrWord]:
        """Recognised words with their boxes, for highlighting text on scanned pages."""
        import pytesseract

        from app.documents.pages import OcrWord, Rect

        data = pytesseract.image_to_data(
            image, lang=self._lang, config="--psm 6", output_type=pytesseract.Output.DICT
        )
        width, height = image.size
        out: list[OcrWord] = []
        for i, raw in enumerate(data["text"]):
            text = str(raw).strip()
            if not text or float(data["conf"][i]) < 0:
                continue
            left, top = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            if w <= 0 or h <= 0:
                continue
            line = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
            rect = Rect(
                x=round(left / width, 5),
                y=round(top / height, 5),
                width=round(w / width, 5),
                height=round(h / height, 5),
            )
            out.append(OcrWord(text=text, line=line, rect=rect))
        return out
