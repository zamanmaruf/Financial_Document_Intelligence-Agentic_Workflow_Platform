"""In-process sliding-window rate limits for the public demo.

State lives in memory, which is correct for the single-task deployment in ``deploy/aws``. Running
more than one replica would need a shared store (e.g. Redis) or the limits multiply per replica.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from starlette.requests import Request

from app.core.errors import RateLimitedError

_MAX_KEYS = 50_000
DAY_S = 86_400


def documents_key(workspace_id: str) -> str:
    return f"docs:{workspace_id}"


def runs_key(workspace_id: str) -> str:
    return f"runs:{workspace_id}"


def questions_key(workspace_id: str) -> str:
    return f"questions:{workspace_id}"


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(
        self, key: str, limit: int, window_s: float, what: str, now: float | None = None
    ) -> None:
        """Record one hit for ``key``; raise ``RateLimitedError`` if over ``limit`` per window."""
        t = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= t - window_s:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, math.ceil(q[0] + window_s - t))
                raise RateLimitedError(f"demo limit reached: {what}", retry_after_s=retry)
            q.append(t)
            if len(self._hits) > _MAX_KEYS:
                self._evict(t)

    def remaining(self, key: str, limit: int, window_s: float, now: float | None = None) -> int:
        t = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            used = sum(1 for ts in q if ts > t - window_s) if q else 0
        return max(0, limit - used)

    def _evict(self, now: float) -> None:
        # Drop keys idle for a day (the longest window used) to bound memory.
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= now - DAY_S]
        for k in stale:
            del self._hits[k]


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """Client address, trusting exactly ``trusted_proxy_hops`` proxies' X-Forwarded-For entries.

    Each trusted proxy appends the address it received the request from, so the real client is
    the entry ``hops`` positions from the right. Entries further left are client-controlled.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(chain) < trusted_proxy_hops:
        return chain[0] if chain else peer
    return chain[-trusted_proxy_hops]
