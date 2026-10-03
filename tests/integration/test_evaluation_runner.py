from __future__ import annotations

import pytest

from app.core.config import Settings
from app.domain.models import GroundednessReport
from app.drift.monitor import DriftSnapshot
from app.evaluation.runner import EvaluationRunner
from app.rag import service as rag_service
from app.rag.groundedness import check_groundedness
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


def test_unsupported_answer_sentences_are_listed_in_failures(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    invented = "The fund also charges a 2.00% performance fee."

    def with_invented_sentence(answer: str, evidence: list[str]) -> GroundednessReport:
        return check_groundedness(f"{answer} {invented}", evidence)

    monkeypatch.setattr(rag_service, "check_groundedness", with_invented_sentence)
    result = EvaluationRunner(settings).run()
    flagged = [
        f for f in result.metrics["failures"]["answers"] if f["issue"] == "unsupported_sentences"
    ]
    assert result.metrics["answers"]["groundedness"] < 1.0
    assert flagged and all(any(invented in s for s in f["sentences"]) for f in flagged)


def test_evaluation_is_deterministic(settings: Settings) -> None:
    a = EvaluationRunner(settings).run()
    b = EvaluationRunner(settings).run()
    for category in ("classification", "extraction", "retrieval", "answers", "workflow"):
        assert a.metrics[category] == b.metrics[category]
