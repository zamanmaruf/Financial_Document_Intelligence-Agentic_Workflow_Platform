from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.classification.service import ClassificationLLMOutput
from app.core.errors import (
    IllegalTransitionError,
    ProviderError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.core.resilience import RetryPolicy
from app.domain.enums import WorkflowStatus
from app.domain.models import ModelInvocation
from app.observability.cost import CostEstimator
from app.observability.logging import JsonFormatter, request_id_var
from app.observability.metrics import InMemoryMetrics, percentile
from app.providers.llm.mock import MockLLMProvider
from app.services.container import Container
from app.services.model_gateway import ModelGateway, extract_json_object
from app.workflows.state_machine import ALLOWED_TRANSITIONS, can_transition
from tests.support import ROOT, ingest

CLASSIFY_VARS = {
    "document_text": "INVOICE\nInvoice Number: 7\nBill To: X\nAmount Due: 10.00",
    "supported_types": "invoice, balance_sheet",
}


class _Sink:
    def __init__(self) -> None:
        self.saved: list[ModelInvocation] = []

    def save(self, inv: ModelInvocation) -> None:
        self.saved.append(inv)


def make_gateway(
    container: Container, provider: MockLLMProvider, **kw: Any
) -> tuple[ModelGateway, _Sink, InMemoryMetrics]:
    sink, metrics = _Sink(), InMemoryMetrics()
    gateway = ModelGateway(
        provider=provider,
        prompts=container.prompts,
        invocations=sink,
        metrics=metrics,
        cost=CostEstimator.load(ROOT / "config"),
        retry_policy=kw.pop("retry_policy", RetryPolicy(max_retries=2, backoff_s=0)),
        **kw,
    )
    return gateway, sink, metrics


def classify(gateway: ModelGateway) -> Any:
    return gateway.invoke(
        "classification.document_type",
        CLASSIFY_VARS,
        ClassificationLLMOutput,
        operation="classification",
    )


class TestModelGateway:
    def test_success_records_invocation(
        self, container: Container, mock_llm_factory: Callable[..., MockLLMProvider]
    ) -> None:
        gateway, sink, _ = make_gateway(container, mock_llm_factory())
        result = classify(gateway)
        assert result.output.document_type == "invoice"
        inv = sink.saved[0]
        assert inv.success and inv.retry_count == 0
        assert inv.prompt_name == "classification.document_type"
        assert inv.prompt_version == "1.0.0"
        assert inv.prompt_hash and inv.is_mock
        assert inv.estimated_cost_usd == 0.0

    def test_transient_failure_is_retried(
        self, container: Container, mock_llm_factory: Callable[..., MockLLMProvider]
    ) -> None:
        gateway, sink, metrics = make_gateway(container, mock_llm_factory(fail_first_n=2))
        classify(gateway)
        assert sink.saved[0].retry_count == 2
        assert metrics.snapshot()["counters"]["llm_retries_total"][0]["value"] == 2

    def test_retries_exhausted(
        self, container: Container, mock_llm_factory: Callable[..., MockLLMProvider]
    ) -> None:
        gateway, sink, _ = make_gateway(container, mock_llm_factory(fail_first_n=10))
        with pytest.raises(ProviderError) as info:
            classify(gateway)
        assert info.value.retries_exhausted
        assert "after 3 attempts" in info.value.message
        assert not sink.saved[0].success

    def test_malformed_json_is_repaired(
        self, container: Container, mock_llm_factory: Callable[..., MockLLMProvider]
    ) -> None:
        provider = mock_llm_factory(malformed_first_n=1)
        gateway, sink, metrics = make_gateway(container, provider, json_repair_attempts=1)
        assert classify(gateway).output.document_type == "invoice"
        assert "previous reply was not a single valid JSON" in provider.calls[-1].user
        assert metrics.snapshot()["counters"]["llm_output_invalid_total"][0]["value"] == 1
        assert sink.saved[0].success

    def test_malformed_json_beyond_repair_budget(
        self, container: Container, mock_llm_factory: Callable[..., MockLLMProvider]
    ) -> None:
        gateway, sink, _ = make_gateway(
            container, mock_llm_factory(malformed_first_n=5), json_repair_attempts=1
        )
        with pytest.raises(ProviderResponseError):
            classify(gateway)
        assert sink.saved[0].error_type == ProviderResponseError.error_type

    def test_timeout(
        self, container: Container, mock_llm_factory: Callable[..., MockLLMProvider]
    ) -> None:
        gateway, _, _ = make_gateway(
            container,
            mock_llm_factory(delay_s=0.3),
            timeout_s=0.05,
            retry_policy=RetryPolicy(max_retries=0, backoff_s=0),
        )
        with pytest.raises(ProviderTimeoutError):
            classify(gateway)

    def test_schema_violation_counts_as_invalid(self, container: Container) -> None:
        class Strict(BaseModel):
            required_field: int

        provider = MockLLMProvider({"classification.document_type": lambda _v: {"x": 1}})
        gateway, _, _ = make_gateway(container, provider, json_repair_attempts=0)
        with pytest.raises(ProviderResponseError):
            gateway.invoke("classification.document_type", CLASSIFY_VARS, Strict, "classification")

    @pytest.mark.parametrize(
        "raw",
        ['{"a": 1}', 'Here you go:\n```json\n{"a": 1}\n```', 'prefix {"a": 1} suffix'],
    )
    def test_extract_json_object(self, raw: str) -> None:
        assert extract_json_object(raw) == {"a": 1}

    def test_extract_json_object_rejects_non_objects(self) -> None:
        with pytest.raises(ValueError):
            extract_json_object("[1, 2]")


class TestObservability:
    def test_metrics_snapshot_and_percentiles(self) -> None:
        m = InMemoryMetrics()
        for v in range(1, 101):
            m.observe("latency_ms", float(v), {"op": "x"})
        m.increment("calls_total", labels={"op": "x"})
        snap = m.snapshot()
        hist = snap["histograms"]["latency_ms"][0]
        assert hist["count"] == 100
        assert hist["p50"] == pytest.approx(50.5)
        assert hist["p95"] == pytest.approx(95.05)
        assert percentile([], 0.5) == 0.0
        prom = m.prometheus_text()
        assert 'docintel_calls_total{op="x"} 1.0' in prom
        assert "_total_total" not in prom

    def test_json_logs_include_context_and_redact(self) -> None:
        record = logging.LogRecord(
            "app.test",
            logging.INFO,
            __file__,
            1,
            "customer ops@bank.example acct 1234567890",
            None,
            None,
        )
        record.fields = {"event": "x", "api_key": "sk-secret", "latency_ms": 12.5}
        token = request_id_var.set("req-123")
        try:
            payload = json.loads(JsonFormatter().format(record))
        finally:
            request_id_var.reset(token)
        assert payload["request_id"] == "req-123"
        assert payload["api_key"] == "[REDACTED]"
        assert "ops@bank.example" not in payload["message"]
        assert "1234567890" not in payload["message"]
        assert payload["latency_ms"] == 12.5

    def test_cost_estimation(self) -> None:
        cost = CostEstimator.load(ROOT / "config")
        estimate = cost.estimate("anthropic.claude-3-5-sonnet-20240620-v1:0", 1000, 1000)
        assert estimate == pytest.approx(0.018)
        assert cost.estimate("unknown-model", 1000, 1000) is None
        assert not cost.known("unknown-model")

    def test_unpriced_model_is_not_reported_as_free(
        self,
        container: Container,
        mock_llm_factory: Callable[..., MockLLMProvider],
        tmp_path: Path,
    ) -> None:
        (tmp_path / "pricing.yaml").write_text("models: {}\n", encoding="utf-8")
        sink, metrics = _Sink(), InMemoryMetrics()
        gateway = ModelGateway(
            provider=mock_llm_factory(),
            prompts=container.prompts,
            invocations=sink,
            metrics=metrics,
            cost=CostEstimator.load(tmp_path),
            retry_policy=RetryPolicy(max_retries=0, backoff_s=0),
        )
        classify(gateway)
        assert sink.saved[0].estimated_cost_usd is None
        counters = metrics.snapshot()["counters"]
        assert "llm_estimated_cost_usd_total" not in counters
        assert counters["llm_unpriced_calls_total"][0]["value"] == 1


class TestAuditChain:
    def test_chain_verifies_and_detects_tampering(self, container: Container) -> None:
        for i in range(3):
            container.audit.record("test.event", document_id="doc_x", details={"i": i})
        ok, broken = container.audit.verify_chain()
        assert ok and broken is None

        events = container.audit.history(document_id="doc_x")
        assert [e.details["i"] for e in events] == [0, 1, 2]
        assert events[1].prev_hash == events[0].event_hash

        with container.engine.begin() as conn:
            row = conn.execute(
                text("SELECT sequence, payload FROM audit_events WHERE sequence = :s"),
                {"s": events[1].sequence},
            ).one()
            payload = json.loads(row.payload)
            payload["details"]["i"] = 99
            conn.execute(
                text("UPDATE audit_events SET payload = :p WHERE sequence = :s"),
                {"p": json.dumps(payload), "s": row.sequence},
            )
        ok, broken = container.audit.verify_chain()
        assert not ok
        assert broken == events[1].sequence

    def test_details_are_redacted(self, container: Container) -> None:
        container.audit.record("x", details={"note": "acct 1234567890", "token": "abc"})
        event = container.audit.history()[-1]
        assert event.details == {"note": "acct ****7890", "token": "[REDACTED]"}


class TestStateMachine:
    def test_transition_table(self) -> None:
        assert can_transition(WorkflowStatus.INGESTED, WorkflowStatus.TEXT_EXTRACTED)
        assert can_transition(WorkflowStatus.NEEDS_REVIEW, WorkflowStatus.READY)
        assert not can_transition(WorkflowStatus.INGESTED, WorkflowStatus.READY)
        assert not can_transition(WorkflowStatus.REJECTED, WorkflowStatus.READY)
        # every status is reachable-from and has an exit (no dead ends)
        assert set(ALLOWED_TRANSITIONS) == set(WorkflowStatus)

    def test_illegal_transition_raises_and_legal_is_audited(self, container: Container) -> None:
        doc = ingest(container, "invoice_01_acme.pdf")
        sm = container.workflow._sm
        with pytest.raises(IllegalTransitionError):
            sm.transition(doc, WorkflowStatus.READY)
        sm.transition(doc, WorkflowStatus.FAILED, "test")
        events = container.audit.history(document_id=doc.document_id)
        assert events[-1].event_type == "workflow.transition"
        assert events[-1].details["to"] == "FAILED"
