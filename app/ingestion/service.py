"""Document upload: validation, de-duplication, secure storage, metadata, audit."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import PurePath

from app.audit.service import SYSTEM_ACTOR, AuditService
from app.core.clock import new_id
from app.core.errors import InvalidDocumentError
from app.core.hashing import sha256_bytes
from app.domain.models import DEFAULT_WORKSPACE, Document, DocumentMetadata
from app.ingestion.pdf import inspect_pdf
from app.observability.logging import log_event
from app.observability.metrics import MetricsRecorder
from app.persistence.repositories import DocumentRepository
from app.providers.storage.local import DocumentStore

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
ALLOWED_CONTENT_TYPES = frozenset(
    {"application/pdf", "application/x-pdf", "application/octet-stream"}
)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(filename: str | None) -> str:
    """Strip any path components and unsafe characters; the name is display-only metadata."""
    base = PurePath((filename or "").replace("\\", "/")).name
    cleaned = _SAFE_NAME_RE.sub("_", base).strip(" .")
    return (cleaned or "document.pdf")[:200]


@dataclass(frozen=True)
class UploadOutcome:
    document: Document
    duplicate: bool


class IngestionService:
    def __init__(
        self,
        documents: DocumentRepository,
        store: DocumentStore,
        audit: AuditService,
        metrics: MetricsRecorder,
        max_upload_bytes: int,
        max_pages: int,
    ) -> None:
        self._documents = documents
        self._store = store
        self._audit = audit
        self._metrics = metrics
        self._max_bytes = max_upload_bytes
        self._max_pages = max_pages

    def validate(self, filename: str | None, content_type: str | None, data: bytes) -> str:
        name = sanitize_filename(filename)
        if not data:
            raise InvalidDocumentError("uploaded file is empty")
        if len(data) > self._max_bytes:
            raise InvalidDocumentError(
                f"file exceeds maximum upload size of {self._max_bytes / (1024 * 1024):g} MB"
            )
        if not name.lower().endswith(".pdf"):
            raise InvalidDocumentError("only .pdf files are accepted")
        if content_type and content_type.split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
            raise InvalidDocumentError(f"unsupported content type '{content_type}'")
        # magic bytes are authoritative; the declared content type is client-controlled
        if not data[:1024].lstrip().startswith(PDF_MAGIC):
            raise InvalidDocumentError("file content is not a PDF")
        return name

    def upload(
        self,
        filename: str | None,
        content_type: str | None,
        data: bytes,
        actor: str = SYSTEM_ACTOR,
        workspace_id: str = DEFAULT_WORKSPACE,
    ) -> UploadOutcome:
        try:
            name = self.validate(filename, content_type, data)
            inspection = inspect_pdf(data)
            if inspection.page_count == 0:
                raise InvalidDocumentError("PDF has no pages")
            if inspection.page_count > self._max_pages:
                raise InvalidDocumentError(f"PDF exceeds {self._max_pages} pages")
        except InvalidDocumentError as exc:
            self._metrics.increment("documents_rejected_total", labels={"reason": exc.error_type})
            log_event(
                logger,
                "upload_rejected",
                logging.WARNING,
                error_type=exc.error_type,
                reason=exc.message,
                size_bytes=len(data),
            )
            raise

        digest = sha256_bytes(data)
        existing = self._documents.find_by_sha256(digest, workspace_id)
        if existing is not None:
            self._metrics.increment("documents_duplicate_total")
            self._audit.record(
                "document.duplicate_upload",
                actor=actor,
                document_id=existing.document_id,
                details={"filename": name, "sha256": digest},
            )
            return UploadOutcome(document=existing, duplicate=True)

        document_id = new_id("doc")
        self._store.save(document_id, data)
        flags = ["pdf_active_content"] if inspection.has_active_content else []
        doc = Document(
            document_id=document_id,
            metadata=DocumentMetadata(
                filename=name,
                content_type="application/pdf",
                size_bytes=len(data),
                sha256=digest,
                page_count=inspection.page_count,
                has_text_layer=inspection.has_text_layer,
                pdf_producer=inspection.producer,
                pdf_title=inspection.title,
            ),
            security_flags=flags,
            workspace_id=workspace_id,
        )
        self._documents.add(doc)
        self._metrics.increment("documents_uploaded_total")
        self._metrics.observe("document_size_bytes", float(len(data)))
        self._audit.record(
            "document.uploaded",
            actor=actor,
            document_id=document_id,
            details={
                "filename": name,
                "sha256": digest,
                "size_bytes": len(data),
                "page_count": inspection.page_count,
                "has_text_layer": inspection.has_text_layer,
                "security_flags": flags,
            },
        )
        log_event(
            logger,
            "document_uploaded",
            document_id=document_id,
            size_bytes=len(data),
            page_count=inspection.page_count,
        )
        return UploadOutcome(document=doc, duplicate=False)
