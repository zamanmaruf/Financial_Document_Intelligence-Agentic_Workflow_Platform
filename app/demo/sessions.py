"""Signed, stateless visitor sessions for the public demo.

A session cookie is ``<workspace_id>.<issued_unix>.<hmac_sha256_hex>``. The server keeps no
session table: the HMAC proves the workspace id was issued here, and ``issued_unix`` bounds the
lifetime. Workspace ids are random and unguessable, so they also act as the visitor's identity.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

COOKIE_NAME = "docintel_demo"
_WORKSPACE_RE = re.compile(r"^ws_[0-9a-f]{24}$")


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def new_workspace_id() -> str:
    return f"ws_{secrets.token_hex(12)}"


def issue_session(secret: str, now: float | None = None) -> tuple[str, str]:
    """Return ``(workspace_id, cookie_value)`` for a fresh visitor."""
    workspace_id = new_workspace_id()
    issued = int(time.time() if now is None else now)
    payload = f"{workspace_id}.{issued}"
    return workspace_id, f"{payload}.{_sign(secret, payload)}"


def verify_session(
    secret: str, value: str | None, ttl_seconds: int, now: float | None = None
) -> str | None:
    """Return the workspace id for a valid, unexpired cookie; ``None`` otherwise."""
    if not value or len(value) > 200:
        return None
    parts = value.split(".")
    if len(parts) != 3:
        return None
    workspace_id, issued_raw, signature = parts
    if not _WORKSPACE_RE.fullmatch(workspace_id) or not issued_raw.isdigit():
        return None
    expected = _sign(secret, f"{workspace_id}.{issued_raw}")
    if not hmac.compare_digest(expected, signature):
        return None
    age = (time.time() if now is None else now) - int(issued_raw)
    if age < 0 or age > ttl_seconds:
        return None
    return workspace_id
