from __future__ import annotations

import uuid
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Opaque unique identifier with a readable type prefix, e.g. ``doc_3f2a...``."""
    return f"{prefix}_{uuid.uuid4().hex}"
