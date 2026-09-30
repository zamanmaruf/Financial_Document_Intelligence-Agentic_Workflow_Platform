"""Local filesystem document store with atomic, owner-only writes.

Production replacement: S3 / Azure Blob with SSE-KMS encryption, bucket policies and lifecycle
rules for retention. The ``DocumentStore`` protocol is the seam.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from app.core.errors import DocumentNotFoundError, InvalidDocumentError

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{32}$")


class DocumentStore(Protocol):
    def save(self, document_id: str, data: bytes) -> str: ...

    def load(self, document_id: str) -> bytes: ...

    def delete(self, document_id: str) -> None: ...


class LocalDocumentStore:
    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir.resolve()
        self._base.mkdir(parents=True, exist_ok=True)
        os.chmod(self._base, 0o700)

    def _path(self, document_id: str) -> Path:
        # Only server-generated ids are accepted, which rules out path traversal entirely.
        if not _DOC_ID_RE.fullmatch(document_id):
            raise InvalidDocumentError("invalid document id")
        path = (self._base / f"{document_id}.pdf").resolve()
        if path.parent != self._base:
            raise InvalidDocumentError("invalid document path")
        return path

    def save(self, document_id: str, data: bytes) -> str:
        path = self._path(document_id)
        fd, tmp = tempfile.mkstemp(dir=self._base, prefix=".upload-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return str(path)

    def load(self, document_id: str) -> bytes:
        path = self._path(document_id)
        if not path.exists():
            raise DocumentNotFoundError(f"stored file for {document_id} not found")
        return path.read_bytes()

    def delete(self, document_id: str) -> None:
        self._path(document_id).unlink(missing_ok=True)
