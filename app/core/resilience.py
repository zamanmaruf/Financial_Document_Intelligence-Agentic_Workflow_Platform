"""Retry and timeout primitives for calls to external providers.

Kept dependency-free and explicit so retry behaviour is easy to test and reason about:
bounded attempts, exponential backoff, and an allow-list of retryable exception types.
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.errors import ProviderTimeoutError

# A shared pool so timed-out calls don't block the caller. A timed-out worker thread keeps
# running until the underlying SDK call returns; SDK-level timeouts should also be set.
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="provider")


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2
    backoff_s: float = 0.5
    backoff_multiplier: float = 2.0
    max_backoff_s: float = 8.0

    def delay_for(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        delay = self.backoff_s * (self.backoff_multiplier ** (attempt - 1))
        return float(min(delay, self.max_backoff_s))


@dataclass
class CallOutcome[R]:
    value: R
    attempts: int

    @property
    def retry_count(self) -> int:
        return self.attempts - 1


class RetriesExhaustedError(Exception):
    def __init__(self, last_error: BaseException, attempts: int) -> None:
        super().__init__(f"retries exhausted after {attempts} attempts: {last_error!r}")
        self.last_error = last_error
        self.attempts = attempts


def call_with_timeout[R](fn: Callable[[], R], timeout_s: float) -> R:
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise ProviderTimeoutError(f"provider call exceeded {timeout_s:.1f}s timeout") from exc


def retry_call[R](
    fn: Callable[[], R],
    policy: RetryPolicy,
    retry_on: tuple[type[BaseException], ...],
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> CallOutcome[R]:
    """Call ``fn`` with bounded retries on the given exception types.

    Raises ``RetriesExhaustedError`` wrapping the last error once attempts run out.
    Non-retryable exceptions propagate immediately.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return CallOutcome(value=fn(), attempts=attempt)
        except retry_on as exc:
            if attempt > policy.max_retries:
                raise RetriesExhaustedError(exc, attempt) from exc
            if on_retry is not None:
                on_retry(attempt, exc)
            sleep(policy.delay_for(attempt))
