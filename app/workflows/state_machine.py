"""Explicit document workflow state machine.

Every status change goes through ``transition``, which rejects moves that are not in the
allowed-transitions table and emits an audit event. This makes the processing path enumerable,
testable and explainable to auditors, in contrast to an open-ended agent loop.
"""

from __future__ import annotations

from app.audit.service import AuditService
from app.core.clock import utcnow
from app.core.errors import IllegalTransitionError
from app.domain.enums import WorkflowStatus as S
from app.domain.models import Document, WorkflowState, WorkflowTransition
from app.persistence.repositories import DocumentRepository, WorkflowRepository

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.INGESTED: frozenset({S.TEXT_EXTRACTED, S.NEEDS_REVIEW, S.FAILED}),
    S.TEXT_EXTRACTED: frozenset({S.CLASSIFIED, S.FAILED}),
    S.CLASSIFIED: frozenset({S.ENTITIES_EXTRACTED, S.FAILED}),
    S.ENTITIES_EXTRACTED: frozenset({S.VALIDATED, S.FAILED}),
    S.VALIDATED: frozenset({S.INDEXED, S.FAILED}),
    S.INDEXED: frozenset({S.READY, S.NEEDS_REVIEW, S.FAILED}),
    S.NEEDS_REVIEW: frozenset({S.READY, S.REJECTED, S.INGESTED}),
    S.READY: frozenset({S.INGESTED}),  # reprocess
    S.REJECTED: frozenset({S.INGESTED}),  # reprocess
    S.FAILED: frozenset({S.INGESTED}),  # retry
}

IN_PROGRESS = frozenset(
    {S.TEXT_EXTRACTED, S.CLASSIFIED, S.ENTITIES_EXTRACTED, S.VALIDATED, S.INDEXED}
)
QUERYABLE = frozenset({S.READY, S.NEEDS_REVIEW})


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


class WorkflowStateMachine:
    def __init__(
        self, documents: DocumentRepository, workflows: WorkflowRepository, audit: AuditService
    ) -> None:
        self._documents = documents
        self._workflows = workflows
        self._audit = audit

    def transition(
        self,
        document: Document,
        target: S,
        reason: str | None = None,
        state: WorkflowState | None = None,
        actor: str = "system",
    ) -> Document:
        current = document.status
        if not can_transition(current, target):
            raise IllegalTransitionError(
                f"illegal transition {current.value} -> {target.value} for {document.document_id}"
            )
        document.status = target
        document.updated_at = utcnow()
        self._documents.update(document)
        if state is not None:
            state.status = target
            state.history.append(
                WorkflowTransition(from_status=current, to_status=target, reason=reason)
            )
            self._workflows.save(state)
        self._audit.record(
            "workflow.transition",
            actor=actor,
            document_id=document.document_id,
            workflow_id=state.workflow_id if state else document.current_workflow_id,
            details={"from": current.value, "to": target.value, "reason": reason},
        )
        return document
