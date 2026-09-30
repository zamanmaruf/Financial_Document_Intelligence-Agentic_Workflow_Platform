from __future__ import annotations

from app.core.config import Settings
from app.drift.monitor import DriftSnapshot
from app.evaluation.runner import EvaluationRunner
from app.services.container import Container


def test_offline_evaluation_passes_quality_gate(settings: Settings) -> None:
    captured: list[DriftSnapshot] = []

    def inspect(c: Container) -> None:
        captured.append(c.drift.snapshot())

    result = EvaluationRunner(settings).run(inspect=inspect)
    assert result.is_mock
    assert result.gate_passed, result.gate_failures
    for category in ("classification", "extraction", "retrieval", "answers", "workflow"):
        assert category in result.metrics
    assert result.metrics["answers"]["unsupported_statement_rate"] == 0.0
    assert result.metrics["answers"]["correct_refusal_rate"] == 1.0
    assert captured and captured[0].counts["documents"] > 0


def test_evaluation_is_deterministic(settings: Settings) -> None:
    a = EvaluationRunner(settings).run()
    b = EvaluationRunner(settings).run()
    for category in ("classification", "extraction", "retrieval", "answers", "workflow"):
        assert a.metrics[category] == b.metrics[category]
