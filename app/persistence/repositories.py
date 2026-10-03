"""Repositories: the only code that touches SQL. Services receive these via the container."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import DocumentNotFoundError, ReviewNotFoundError
from app.domain.enums import ReviewStatus
from app.domain.models import (
    DEFAULT_WORKSPACE,
    AuditEvent,
    Document,
    EvaluationResult,
    ExtractedText,
    ExtractionResult,
    ModelInvocation,
    RAGAnswer,
    ReviewCase,
    WorkflowState,
)
from app.persistence.db import (
    AnswerRow,
    AuditRow,
    DocumentRow,
    DocumentTextRow,
    EvaluationRow,
    ExtractionRow,
    InvocationRow,
    ReviewRow,
    WorkflowRow,
)


def _dump(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


class _Repo:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory


class DocumentRepository(_Repo):
    def add(self, doc: Document) -> None:
        with self._sf.begin() as s:
            s.add(
                DocumentRow(
                    document_id=doc.document_id,
                    workspace_id=doc.workspace_id,
                    sha256=doc.metadata.sha256,
                    status=doc.status.value,
                    document_type=doc.document_type.value if doc.document_type else None,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                    payload=_dump(doc),
                )
            )

    def update(self, doc: Document) -> None:
        with self._sf.begin() as s:
            row = s.get(DocumentRow, doc.document_id)
            if row is None:
                raise DocumentNotFoundError(doc.document_id)
            row.status = doc.status.value
            row.document_type = doc.document_type.value if doc.document_type else None
            row.updated_at = doc.updated_at
            row.payload = _dump(doc)

    def get(self, document_id: str) -> Document:
        with self._sf() as s:
            row = s.get(DocumentRow, document_id)
            if row is None:
                raise DocumentNotFoundError(f"document {document_id} not found")
            return Document.model_validate(row.payload)

    def find_by_sha256(self, sha256: str, workspace_id: str = DEFAULT_WORKSPACE) -> Document | None:
        with self._sf() as s:
            row = s.scalars(
                select(DocumentRow).where(
                    DocumentRow.sha256 == sha256, DocumentRow.workspace_id == workspace_id
                )
            ).first()
            return Document.model_validate(row.payload) if row else None

    def list_page(
        self, limit: int = 100, offset: int = 0, workspace_id: str | None = None
    ) -> list[Document]:
        """Newest first; ``workspace_id=None`` lists every workspace (operators only)."""
        with self._sf() as s:
            q = select(DocumentRow)
            if workspace_id is not None:
                q = q.where(DocumentRow.workspace_id == workspace_id)
            rows = s.scalars(
                q.order_by(DocumentRow.created_at.desc()).limit(limit).offset(offset)
            ).all()
            return [Document.model_validate(r.payload) for r in rows]

    def all(self) -> list[Document]:
        with self._sf() as s:
            return [Document.model_validate(r.payload) for r in s.scalars(select(DocumentRow))]


class DocumentTextRepository(_Repo):
    def save(self, document_id: str, text: ExtractedText) -> None:
        with self._sf.begin() as s:
            s.merge(DocumentTextRow(document_id=document_id, payload=_dump(text)))

    def get(self, document_id: str) -> ExtractedText | None:
        with self._sf() as s:
            row = s.get(DocumentTextRow, document_id)
            return ExtractedText.model_validate(row.payload) if row else None


class ExtractionRepository(_Repo):
    def save(self, result: ExtractionResult) -> None:
        with self._sf.begin() as s:
            s.merge(
                ExtractionRow(
                    extraction_id=result.extraction_id,
                    document_id=result.document_id,
                    created_at=result.created_at,
                    payload=_dump(result),
                )
            )

    def list_for_document(self, document_id: str) -> list[ExtractionResult]:
        with self._sf() as s:
            rows = s.scalars(
                select(ExtractionRow)
                .where(ExtractionRow.document_id == document_id)
                .order_by(ExtractionRow.created_at.desc())
            ).all()
            return [ExtractionResult.model_validate(r.payload) for r in rows]

    def latest_for_document(self, document_id: str) -> ExtractionResult | None:
        items = self.list_for_document(document_id)
        return items[0] if items else None

    def get(self, extraction_id: str) -> ExtractionResult | None:
        with self._sf() as s:
            row = s.get(ExtractionRow, extraction_id)
            return ExtractionResult.model_validate(row.payload) if row else None

    def all(self) -> list[ExtractionResult]:
        with self._sf() as s:
            return [
                ExtractionResult.model_validate(r.payload) for r in s.scalars(select(ExtractionRow))
            ]


class WorkflowRepository(_Repo):
    def save(self, state: WorkflowState) -> None:
        with self._sf.begin() as s:
            s.merge(
                WorkflowRow(
                    workflow_id=state.workflow_id,
                    document_id=state.document_id,
                    status=state.status.value,
                    started_at=state.started_at,
                    payload=_dump(state),
                )
            )

    def get(self, workflow_id: str) -> WorkflowState | None:
        with self._sf() as s:
            row = s.get(WorkflowRow, workflow_id)
            return WorkflowState.model_validate(row.payload) if row else None


class ReviewRepository(_Repo):
    def save(self, case: ReviewCase) -> None:
        with self._sf.begin() as s:
            s.merge(
                ReviewRow(
                    review_id=case.review_id,
                    workspace_id=case.workspace_id,
                    document_id=case.document_id,
                    status=case.status.value,
                    target_type=case.target_type.value,
                    created_at=case.created_at,
                    payload=_dump(case),
                )
            )

    def get(self, review_id: str) -> ReviewCase:
        with self._sf() as s:
            row = s.get(ReviewRow, review_id)
            if row is None:
                raise ReviewNotFoundError(f"review {review_id} not found")
            return ReviewCase.model_validate(row.payload)

    def search(
        self,
        status: ReviewStatus | None = None,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        workspace_id: str | None = None,
    ) -> list[ReviewCase]:
        with self._sf() as s:
            q = select(ReviewRow)
            if workspace_id is not None:
                q = q.where(ReviewRow.workspace_id == workspace_id)
            if status is not None:
                q = q.where(ReviewRow.status == status.value)
            if document_id is not None:
                q = q.where(ReviewRow.document_id == document_id)
            rows = s.scalars(q.order_by(ReviewRow.created_at.desc()).limit(limit).offset(offset))
            return [ReviewCase.model_validate(r.payload) for r in rows.all()]

    def all(self) -> list[ReviewCase]:
        with self._sf() as s:
            return [ReviewCase.model_validate(r.payload) for r in s.scalars(select(ReviewRow))]


class AuditRepository(_Repo):
    """Append-only. There is intentionally no update or delete method."""

    _lock = threading.Lock()

    def last_hash(self) -> str:
        with self._sf() as s:
            row = s.scalars(select(AuditRow).order_by(AuditRow.sequence.desc()).limit(1)).first()
            return row.event_hash if row else ""

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._sf.begin() as s:
            row = AuditRow(
                event_id=event.event_id,
                document_id=event.document_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                event_hash=event.event_hash,
                payload=_dump(event),
            )
            s.add(row)
            s.flush()
            event = event.model_copy(update={"sequence": row.sequence})
            row.payload = _dump(event)
        return event

    def events(self, document_id: str | None = None, limit: int = 1000) -> list[AuditEvent]:
        with self._sf() as s:
            q = select(AuditRow)
            if document_id is not None:
                q = q.where(AuditRow.document_id == document_id)
            rows = s.scalars(q.order_by(AuditRow.sequence.asc()).limit(limit)).all()
            return [AuditEvent.model_validate(r.payload) for r in rows]


class InvocationRepository(_Repo):
    def save(self, inv: ModelInvocation) -> None:
        with self._sf.begin() as s:
            s.add(
                InvocationRow(
                    invocation_id=inv.invocation_id,
                    operation=inv.operation,
                    created_at=inv.created_at,
                    payload=_dump(inv),
                )
            )

    def all(self) -> list[ModelInvocation]:
        with self._sf() as s:
            return [
                ModelInvocation.model_validate(r.payload) for r in s.scalars(select(InvocationRow))
            ]

    def count(self) -> int:
        with self._sf() as s:
            return int(s.scalar(select(func.count()).select_from(InvocationRow)) or 0)

    def live_cost_since(self, since: datetime) -> float:
        """Estimated USD spent on non-mock model calls recorded at or after ``since``."""
        with self._sf() as s:
            rows = s.scalars(select(InvocationRow).where(InvocationRow.created_at >= since))
            total = 0.0
            for row in rows:
                inv = row.payload
                if not inv.get("is_mock", False):
                    total += float(inv.get("estimated_cost_usd") or 0.0)
            return total


class AnswerRepository(_Repo):
    def save(self, answer: RAGAnswer) -> None:
        with self._sf.begin() as s:
            s.merge(
                AnswerRow(
                    answer_id=answer.answer_id,
                    workspace_id=answer.workspace_id,
                    document_id=answer.document_id,
                    created_at=answer.created_at,
                    payload=_dump(answer),
                )
            )

    def get(self, answer_id: str) -> RAGAnswer | None:
        with self._sf() as s:
            row = s.get(AnswerRow, answer_id)
            return RAGAnswer.model_validate(row.payload) if row else None

    def all(self) -> list[RAGAnswer]:
        with self._sf() as s:
            return [RAGAnswer.model_validate(r.payload) for r in s.scalars(select(AnswerRow))]


class EvaluationRepository(_Repo):
    def save(self, result: EvaluationResult) -> None:
        with self._sf.begin() as s:
            s.merge(
                EvaluationRow(
                    run_id=result.run_id, created_at=result.created_at, payload=_dump(result)
                )
            )

    def recent(self, limit: int = 50) -> list[EvaluationResult]:
        with self._sf() as s:
            rows = s.scalars(
                select(EvaluationRow).order_by(EvaluationRow.created_at.desc()).limit(limit)
            ).all()
            return [EvaluationResult.model_validate(r.payload) for r in rows]


class RetentionRepository(_Repo):
    """Deletes expired public-demo visitor data. The default workspace is never touched.

    Audit events are append-only and are kept (see ``app.demo.retention``).
    """

    def expired_document_ids(self, cutoff: datetime) -> list[str]:
        with self._sf() as s:
            return list(
                s.scalars(
                    select(DocumentRow.document_id).where(
                        DocumentRow.workspace_id != DEFAULT_WORKSPACE,
                        DocumentRow.created_at < cutoff,
                    )
                )
            )

    def purge(self, document_ids: list[str], cutoff: datetime) -> dict[str, int]:
        """Delete the given documents with their derived rows, plus expired visitor
        reviews and answers. Returns deleted row counts per table."""
        counts: dict[str, int] = {}
        with self._sf.begin() as s:
            for name, model in (
                ("document_texts", DocumentTextRow),
                ("extractions", ExtractionRow),
                ("workflows", WorkflowRow),
                ("documents", DocumentRow),
            ):
                result = s.execute(delete(model).where(model.document_id.in_(document_ids)))
                counts[name] = int(getattr(result, "rowcount", 0) or 0)
            for name, row_model in (("reviews", ReviewRow), ("answers", AnswerRow)):
                result = s.execute(
                    delete(row_model).where(
                        row_model.workspace_id != DEFAULT_WORKSPACE,
                        (row_model.created_at < cutoff) | row_model.document_id.in_(document_ids),
                    )
                )
                counts[name] = int(getattr(result, "rowcount", 0) or 0)
        return counts
