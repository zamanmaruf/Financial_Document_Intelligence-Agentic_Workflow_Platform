"""Append-only, hash-chained audit trail.

Each event stores ``prev_hash`` and ``event_hash = sha256(prev_hash + canonical(event))``. This
makes after-the-fact edits *detectable* (``verify_chain``); it does not make them impossible.
Production would additionally ship events to WORM storage (e.g. S3 Object Lock).
"""

from __future__ import annotations

import threading
from typing import Any

from app.core.clock import new_id, utcnow
from app.core.hashing import sha256_text, stable_json
from app.domain.models import AuditEvent
from app.guardrails.pii import redact_value
from app.persistence.repositories import AuditRepository

SYSTEM_ACTOR = "system"


def _hash_event(event: AuditEvent, prev_hash: str) -> str:
    body = event.model_dump(mode="json", exclude={"sequence", "event_hash", "prev_hash"})
    return sha256_text(prev_hash + stable_json(body))


class AuditService:
    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo
        self._lock = threading.Lock()

    def record(
        self,
        event_type: str,
        actor: str = SYSTEM_ACTOR,
        document_id: str | None = None,
        workflow_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        safe_details = {k: redact_value(k, v) for k, v in (details or {}).items()}
        with self._lock:
            prev = self._repo.last_hash()
            event = AuditEvent(
                event_id=new_id("evt"),
                event_type=event_type,
                actor=actor,
                document_id=document_id,
                workflow_id=workflow_id,
                details=safe_details,
                timestamp=utcnow(),
                prev_hash=prev,
            )
            event = event.model_copy(update={"event_hash": _hash_event(event, prev)})
            return self._repo.append(event)

    def history(self, document_id: str | None = None, limit: int = 1000) -> list[AuditEvent]:
        return self._repo.events(document_id=document_id, limit=limit)

    def verify_chain(self) -> tuple[bool, int | None]:
        """Recompute the full chain. Returns (ok, first_broken_sequence)."""
        prev = ""
        for event in self._repo.events(limit=10_000_000):
            if event.prev_hash != prev or _hash_event(event, prev) != event.event_hash:
                return False, event.sequence
            prev = event.event_hash
        return True, None
