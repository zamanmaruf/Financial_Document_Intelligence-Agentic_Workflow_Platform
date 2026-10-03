"""Daily spend cap for live LLM calls in the public demo.

``BudgetedLLMProvider`` routes each call to the live provider while today's (UTC) estimated
spend is under the cap, and to the offline mock provider once it is reached. Every response
carries the identity of the provider that actually produced it (``is_mock=True`` for the
fallback), so answers, extractions and invocation records stay correctly labelled.

The cap is soft: spend is read from recorded invocations, so calls already in flight when the
cap is crossed still complete (a few cents at most). Costs come from ``config/pricing.yaml``
estimates; embedding calls are not counted.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from datetime import time as dtime

from app.observability.logging import log_event
from app.persistence.repositories import InvocationRepository
from app.providers.llm.base import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

_CACHE_S = 5.0


def utc_midnight(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return datetime.combine(current.date(), dtime.min, tzinfo=UTC)


class DailyBudget:
    def __init__(self, invocations: InvocationRepository, limit_usd: float) -> None:
        self._invocations = invocations
        self.limit_usd = limit_usd
        self._lock = threading.Lock()
        self._cached: tuple[float, float] | None = None  # (monotonic time, spent)

    def spent_today(self) -> float:
        with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached[0] < _CACHE_S:
                return self._cached[1]
            spent = self._invocations.live_cost_since(utc_midnight())
            self._cached = (now, spent)
            return spent

    def exhausted(self) -> bool:
        return self.spent_today() >= self.limit_usd


class BudgetedLLMProvider:
    """LLM provider wrapper: live until the daily cap, then the labelled offline engine."""

    def __init__(self, live: LLMProvider, fallback: LLMProvider, budget: DailyBudget) -> None:
        self._live = live
        self._fallback = fallback
        self.budget = budget
        self._was_exhausted = False

    @property
    def provider_name(self) -> str:
        return self._live.provider_name

    @property
    def model_name(self) -> str:
        return self._live.model_name

    @property
    def is_mock(self) -> bool:
        return self._live.is_mock

    @property
    def live_available(self) -> bool:
        return not self.budget.exhausted()

    def generate(self, request: LLMRequest) -> LLMResponse:
        exhausted = self.budget.exhausted()
        if exhausted != self._was_exhausted:
            self._was_exhausted = exhausted
            log_event(
                logger,
                "demo_budget_state",
                logging.WARNING if exhausted else logging.INFO,
                exhausted=exhausted,
                limit_usd=self.budget.limit_usd,
            )
        if exhausted:
            return self._fallback.generate(request)
        return self._live.generate(request)
