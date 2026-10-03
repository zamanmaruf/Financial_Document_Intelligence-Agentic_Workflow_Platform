"""Deterministic mock LLM provider with fault injection for tests."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable

from app.core.errors import ProviderConfigurationError, ProviderError
from app.providers.llm.base import LLMRequest, LLMResponse, estimate_tokens
from app.providers.llm.mock_handlers import MockHandler

MOCK_MODEL_NAME = "mock-deterministic-v1"


class MockLLMProvider:
    """Returns JSON produced by deterministic handlers keyed by prompt name.

    Fault injection (for resilience tests):
      * ``fail_first_n``: the first N calls raise ``error_factory()``.
      * ``malformed_first_n``: the first N successful calls return non-JSON text.
      * ``delay_s``: sleep before responding (timeout tests).
    """

    def __init__(
        self,
        handlers: dict[str, MockHandler],
        fail_first_n: int = 0,
        malformed_first_n: int = 0,
        delay_s: float = 0.0,
        error_factory: Callable[[], Exception] | None = None,
    ) -> None:
        self._handlers = handlers
        self._fail_remaining = fail_first_n
        self._malformed_remaining = malformed_first_n
        self._delay_s = delay_s
        self._error_factory = error_factory or (lambda: ProviderError("injected mock failure"))
        self._lock = threading.Lock()
        # recent requests, for test assertions; bounded so long-running servers do not grow
        self.calls: deque[LLMRequest] = deque(maxlen=256)

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return MOCK_MODEL_NAME

    @property
    def is_mock(self) -> bool:
        return True

    def generate(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.calls.append(request)
            fail = self._fail_remaining > 0
            if fail:
                self._fail_remaining -= 1
        if self._delay_s:
            time.sleep(self._delay_s)
        if fail:
            raise self._error_factory()

        handler = self._handlers.get(request.prompt_name)
        if handler is None:
            raise ProviderConfigurationError(
                f"mock provider has no handler for prompt '{request.prompt_name}'"
            )
        with self._lock:
            malformed = self._malformed_remaining > 0
            if malformed:
                self._malformed_remaining -= 1
        text = (
            "Sure! Here is the answer you asked for."
            if malformed
            else json.dumps(handler(request.variables), sort_keys=True)
        )
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model_name=self.model_name,
            input_tokens=estimate_tokens(request.system + request.user),
            output_tokens=estimate_tokens(text),
            tokens_estimated=True,
            stop_reason="end_turn",
            is_mock=True,
        )
