"""Page-aware chunking.

Pages are chunked independently so every chunk has a single page number for citations. Text is
PII-masked *before* chunking, so the vector index never contains full account numbers or emails
and chunk offsets refer to the masked page text.
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.hashing import sha256_text
from app.domain.enums import DocumentType
from app.domain.models import Chunk, ExtractedText
from app.guardrails.pii import redact_text


class Chunker:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            add_start_index=True,
            strip_whitespace=True,
        )

    def chunk(
        self,
        document_id: str,
        text: ExtractedText,
        document_type: DocumentType | None = None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        index = 0
        for page in text.pages:
            masked = redact_text(page.text)
            if not masked.strip():
                continue
            for piece in self._splitter.create_documents([masked]):
                content = piece.page_content
                start = int(piece.metadata.get("start_index", 0))
                chunk_id = (
                    "chk_" + sha256_text(f"{document_id}|{page.page_number}|{index}|{content}")[:24]
                )
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        text=content,
                        page_number=page.page_number,
                        chunk_index=index,
                        start_char=start,
                        end_char=start + len(content),
                        metadata={
                            "document_type": (document_type or DocumentType.UNKNOWN).value,
                            "extraction_method": text.method.value,
                        },
                    )
                )
                index += 1
        return chunks
