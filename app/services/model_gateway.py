"""ModelGateway: the single path through which business logic calls an LLM.

Responsibilities:
  1. render a versioned prompt from the registry
  2. call the configured ``LLMProvider`` with a timeout and bounded retries
  3. parse the JSON response and validate it against a Pydantic schema, with a bounded
     "repair" re-prompt when the output is malformed
  4. record a ``ModelInvocation`` (provider, model, prompt version/hash, latency, tokens,
     estimated cost, retries, outcome) to the repository, metrics and structured logs

Business services never talk to a provider directly, which keeps vendor coupling, retry policy
and observability in one reviewed place.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.core.clock import new_id
from app.core.errors import ProviderError, ProviderResponseError
from app.core.resilience import RetriesExhaustedError, RetryPolicy, call_with_timeout, retry_call
from app.domain.models import ModelInvocation
from app.observability.cost import CostEstimator
from app.observability.logging import log_event
from app.observability.metrics import MetricsRecorder
from app.prompts.registry import PromptRegistry, PromptSpec
from app.providers.llm.base import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class InvocationSink(Protocol):
    def save(self, inv: ModelInvocation) -> None: ...


@dataclass
class GatewayResult[T: BaseModel]:
    output: T
    invocation: ModelInvocation
    prompt: PromptSpec


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object in ``text`` (tolerates markdown fences / leading prose)."""
    candidates: list[str] = []
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found in model output")


class ModelGateway:
    def __init__(
        self,
        provider: LLMProvider,
        prompts: PromptRegistry,
        invocations: InvocationSink,
        metrics: MetricsRecorder,
        cost: CostEstimator,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout_s: float = 60.0,
        retry_policy: RetryPolicy | None = None,
        json_repair_attempts: int = 1,
    ) -> None:
        self.provider = provider
        self.prompts = prompts
        self._invocations = invocations
        self._metrics = metrics
        self._cost = cost
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._retry_policy = retry_policy or RetryPolicy()
        self._json_repair_attempts = json_repair_attempts

    def invoke[T: BaseModel](
        self,
        prompt_name: str,
        render_vars: dict[str, Any],
        schema: type[T],
        operation: str,
        structured_vars: dict[str, Any] | None = None,
        document_id: str | None = None,
        workflow_id: str | None = None,
        prompt_version: str | None = None,
    ) -> GatewayResult[T]:
        spec = self.prompts.get(prompt_name, prompt_version)
        system, user = spec.render(**render_vars)
        request = LLMRequest(
            system=system,
            user=user,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            prompt_name=spec.name,
            prompt_version=spec.version,
            variables=structured_vars if structured_vars is not None else render_vars,
        )

        started = time.perf_counter()
        retries = 0
        input_tokens = output_tokens = 0
        tokens_estimated = False
        last_error: Exception | None = None

        for repair_attempt in range(self._json_repair_attempts + 1):
            try:
                response, attempt_retries = self._call_provider(request)
            except ProviderError as exc:
                self._record(
                    spec,
                    operation,
                    started,
                    retries,
                    input_tokens,
                    output_tokens,
                    tokens_estimated,
                    document_id,
                    workflow_id,
                    success=False,
                    error_type=exc.error_type,
                )
                raise
            retries += attempt_retries + (1 if repair_attempt else 0)
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            tokens_estimated = tokens_estimated or response.tokens_estimated
            try:
                output = schema.model_validate(extract_json_object(response.text))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                request = request.model_copy(
                    update={
                        "user": request.user
                        + "\n\nYour previous reply was not a single valid JSON object matching "
                        "the required shape. Reply again with ONLY the JSON object."
                    }
                )
                self._metrics.increment("llm_output_invalid_total", labels={"operation": operation})
                continue
            invocation = self._record(
                spec,
                operation,
                started,
                retries,
                input_tokens,
                output_tokens,
                tokens_estimated,
                document_id,
                workflow_id,
                success=True,
                error_type=None,
            )
            return GatewayResult(output=output, invocation=invocation, prompt=spec)

        self._record(
            spec,
            operation,
            started,
            retries,
            input_tokens,
            output_tokens,
            tokens_estimated,
            document_id,
            workflow_id,
            success=False,
            error_type=ProviderResponseError.error_type,
        )
        raise ProviderResponseError(
            f"{operation}: model output failed schema validation after "
            f"{self._json_repair_attempts + 1} attempts ({type(last_error).__name__})"
        )

    def _call_provider(self, request: LLMRequest) -> tuple[LLMResponse, int]:
        def once() -> LLMResponse:
            return call_with_timeout(lambda: self.provider.generate(request), self._timeout_s)

        def on_retry(attempt: int, exc: BaseException) -> None:
            self._metrics.increment(
                "llm_retries_total", labels={"provider": self.provider.provider_name}
            )
            log_event(
                logger,
                "llm_retry",
                logging.WARNING,
                prompt_name=request.prompt_name,
                attempt=attempt,
                error_type=getattr(exc, "error_type", type(exc).__name__),
            )

        try:
            outcome = retry_call(once, self._retry_policy, (ProviderError,), on_retry=on_retry)
        except RetriesExhaustedError as exc:
            err = exc.last_error
            if isinstance(err, ProviderError):
                err.message = f"{err.message} (after {exc.attempts} attempts)"
                err.retries_exhausted = True
                raise err from exc
            raise ProviderError(str(err)) from exc
        return outcome.value, outcome.retry_count

    def _record(
        self,
        spec: PromptSpec,
        operation: str,
        started: float,
        retries: int,
        input_tokens: int,
        output_tokens: int,
        tokens_estimated: bool,
        document_id: str | None,
        workflow_id: str | None,
        success: bool,
        error_type: str | None,
    ) -> ModelInvocation:
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        provider = self.provider
        inv = ModelInvocation(
            invocation_id=new_id("inv"),
            operation=operation,
            provider=provider.provider_name,
            model_name=provider.model_name,
            prompt_name=spec.name,
            prompt_version=spec.version,
            prompt_hash=spec.hash,
            document_id=document_id,
            workflow_id=workflow_id,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_estimated=tokens_estimated,
            estimated_cost_usd=self._cost.estimate(
                provider.model_name, input_tokens, output_tokens
            ),
            retry_count=retries,
            success=success,
            error_type=error_type,
            is_mock=provider.is_mock,
        )
        try:
            self._invocations.save(inv)
        except Exception:  # observability must never break the business path
            logger.exception("failed to persist model invocation")
        labels = {"provider": inv.provider, "operation": operation, "success": str(success).lower()}
        self._metrics.increment("llm_calls_total", labels=labels)
        self._metrics.observe("llm_latency_ms", latency_ms, labels={"operation": operation})
        self._metrics.increment("llm_input_tokens_total", input_tokens, {"provider": inv.provider})
        self._metrics.increment(
            "llm_output_tokens_total", output_tokens, {"provider": inv.provider}
        )
        if inv.estimated_cost_usd is None:
            self._metrics.increment("llm_unpriced_calls_total", labels={"model": inv.model_name})
        else:
            self._metrics.increment(
                "llm_estimated_cost_usd_total", inv.estimated_cost_usd, {"provider": inv.provider}
            )
        log_event(
            logger,
            "model_invocation",
            logging.INFO if success else logging.WARNING,
            operation=operation,
            model_provider=inv.provider,
            model_name=inv.model_name,
            prompt_name=spec.name,
            prompt_version=spec.version,
            prompt_hash=spec.hash,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_estimated=tokens_estimated,
            estimated_cost=inv.estimated_cost_usd,
            retry_count=retries,
            success=success,
            error_type=error_type,
            is_mock=inv.is_mock,
        )
        return inv
