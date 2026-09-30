"""Deterministic hashing helpers (canonical JSON + SHA-256)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def stable_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no insignificant whitespace, UTF-8 preserved."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_hash(obj: Any) -> str:
    return sha256_text(stable_json(obj))


def short_hash(obj: Any, length: int = 12) -> str:
    return stable_hash(obj)[:length]
