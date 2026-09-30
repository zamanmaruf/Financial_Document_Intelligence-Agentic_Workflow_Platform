"""AWS Textract OCR (synchronous ``DetectDocumentText`` per rendered page).

Requires AWS credentials with ``textract:DetectDocumentText``. Multi-page PDFs are rendered to
PNG page images locally so the synchronous API can be used without staging files in S3; very
large documents should use the asynchronous S3-based API instead (see roadmap).
"""

from __future__ import annotations

import io
from typing import Any

from app.core.errors import ProviderError
from app.domain.enums import TextExtractionMethod
from app.domain.models import ExtractedText, PageText


class TextractOCRExtractor:
    name = "textract"
    method = TextExtractionMethod.OCR_TEXTRACT

    def __init__(self, region: str, client: Any | None = None, dpi: int = 200) -> None:
        self._region = region
        self._client = client
        self._scale = dpi / 72.0

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("textract", region_name=self._region)
        return self._client

    def is_available(self) -> bool:
        return True  # availability is only known at call time (credentials / network)

    def extract(self, data: bytes) -> ExtractedText:
        import pypdfium2 as pdfium

        client = self._get_client()
        pdf = pdfium.PdfDocument(data)
        pages: list[PageText] = []
        try:
            for i in range(len(pdf)):
                buf = io.BytesIO()
                pdf[i].render(scale=self._scale).to_pil().save(buf, format="PNG")
                try:
                    resp = client.detect_document_text(Document={"Bytes": buf.getvalue()})
                except Exception as exc:
                    raise ProviderError(f"Textract failed: {type(exc).__name__}") from exc
                lines = [
                    str(b.get("Text", ""))
                    for b in resp.get("Blocks", [])
                    if b.get("BlockType") == "LINE"
                ]
                pages.append(PageText(page_number=i + 1, text="\n".join(lines)))
        finally:
            pdf.close()
        return ExtractedText(pages=pages, method=self.method)
