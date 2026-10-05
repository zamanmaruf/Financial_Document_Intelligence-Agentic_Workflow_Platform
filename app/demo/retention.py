"""Deletes public-demo visitor data after the retention window.

Removes the stored PDF, vector-index chunks and database rows (document, text, extractions,
workflows, reviews, answers). The append-only audit trail is kept: deleting entries would break
the hash chain. It holds ids, hashes, filenames, decisions (including reviewer-corrected values)
and short excerpts flagged by the injection scanner, not the documents or their full text. Data in
the default workspace is never deleted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.clock import utcnow
from app.observability.logging import log_event
from app.services.container import Container

logger = logging.getLogger(__name__)

PURGE_INTERVAL_S = 900


def purge_expired(container: Container, now: datetime | None = None) -> dict[str, int]:
    cutoff = (now or utcnow()) - timedelta(hours=container.settings.demo_retention_hours)
    ids = [
        doc_id
        for doc_id in container.retention.expired_document_ids(cutoff)
        if not container.jobs.is_running(doc_id)
    ]
    for doc_id in ids:
        container.vector_store.delete_document(doc_id)
        container.store.delete(doc_id)
        container.pages.forget(doc_id)
    counts = container.retention.purge(ids, cutoff)
    if any(counts.values()):
        container.audit.record(
            "demo.retention_purge",
            details={"cutoff": cutoff.isoformat(), "deleted": counts},
        )
        log_event(logger, "demo_retention_purge", **counts)
    return counts
