"""Bounded background execution for document processing.

Processing a document makes several model calls; running it in a small worker pool keeps API
request threads free and lets the UI poll progress (``GET /documents/{id}`` reports each
workflow state as the orchestrator persists it). At most one job per document runs at a time.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from app.core.errors import InvalidStateError

logger = logging.getLogger(__name__)


class BackgroundJobs:
    def __init__(self, max_workers: int = 2) -> None:
        self._max_workers = max_workers
        self._pool: ThreadPoolExecutor | None = None
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def is_running(self, key: str) -> bool:
        with self._lock:
            return key in self._running

    def submit(self, key: str, fn: Callable[[], object]) -> Future[object]:
        with self._lock:
            if key in self._running:
                raise InvalidStateError(f"{key} is already being processed")
            if self._pool is None:
                self._pool = ThreadPoolExecutor(
                    max_workers=self._max_workers, thread_name_prefix="docintel-job"
                )
            self._running.add(key)

        def run() -> object:
            try:
                return fn()
            except Exception:
                # The workflow records its own FAILED state and audit event; this is a backstop.
                logger.exception("background job failed", extra={"fields": {"job": key}})
                raise
            finally:
                with self._lock:
                    self._running.discard(key)

        return self._pool.submit(run)

    def shutdown(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
