from __future__ import annotations

import pytest

from app.drift.monitor import DriftMonitor, DriftSnapshot, DriftThresholds, histogram, psi
from app.evaluation.gate import Thresholds, evaluate_gate
from app.evaluation.metrics import (
    answer_completeness,
    classification_metrics,
    extraction_metrics,
    fact_present,
    retrieval_query_metrics,
    values_normalized_match,
)


class TestClassificationMetrics:
    def test_perfect(self) -> None:
        m = classification_metrics(["a", "b"], ["a", "b"])
        assert m["accuracy"] == 1.0
        assert m["macro_f1"] == 1.0

    def test_confusion_and_macro(self) -> None:
        m = classification_metrics(["a", "a", "b", "b"], ["a", "b", "b", "b"])
        assert m["accuracy"] == 0.75
        assert m["confusion_matrix"]["a"]["b"] == 1
        assert m["per_class"]["a"]["recall"] == 0.5
        assert m["per_class"]["b"]["precision"] == pytest.approx(0.6667, abs=1e-4)

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="equal length"):
            classification_metrics(["a"], [])


class TestExtractionMetrics:
    def test_rates(self) -> None:
        items = [
            {"document_type": "invoice", "field": "tax", "expected": 8.0, "predicted": 8.0},
            {"document_type": "invoice", "field": "subtotal", "expected": 100.0, "predicted": None},
            {"document_type": "invoice", "field": "po", "expected": None, "predicted": "PO-1"},
            {
                "document_type": "invoice",
                "field": "vendor",
                "expected": "Acme",
                "predicted": " acme ",
                "validation_status": "invalid",
            },
        ]
        m = extraction_metrics(items)
        assert m["exact_match"] == pytest.approx(1 / 3, abs=1e-4)
        assert m["normalized_match"] == pytest.approx(2 / 3, abs=1e-4)
        assert m["missing_field_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert m["hallucinated_field_rate"] == 1.0
        assert m["invalid_value_rate"] == pytest.approx(1 / 3, abs=1e-4)

    def test_normalized_match_is_sign_insensitive_with_tolerance(self) -> None:
        assert values_normalized_match(-1000.0, 1000.0)
        assert values_normalized_match(1000.0, 1004.0)
        assert not values_normalized_match(1000.0, 1100.0)
        assert values_normalized_match(None, None)
        assert not values_normalized_match("x", None)


class TestRetrievalAndAnswerMetrics:
    def test_retrieval_query_metrics(self) -> None:
        m = retrieval_query_metrics([False, True, False, False], total_relevant=1, k=4)
        assert m == {"precision_at_k": 0.25, "recall_at_k": 1.0, "hit": 1.0, "reciprocal_rank": 0.5}
        assert retrieval_query_metrics([], 1, 4)["hit"] == 0.0

    def test_fact_matching_is_numeric_aware(self) -> None:
        assert fact_present("5,238.00", "The amount due is $5238.")
        assert fact_present("Net 30", "payment terms are net 30 days")
        assert not fact_present("5,238.00", "The amount due is 5,300.")
        assert answer_completeness(["5,238.00", "USD"], "Amount due 5,238.00") == 0.5


class TestQualityGate:
    THRESHOLDS = Thresholds(
        limits={"a.score": {"min": 0.8}, "a.error_rate": {"max": 0.1}},
        regression_metrics=["a.score", "a.error_rate"],
        tolerance=0.03,
    )

    def test_passes(self) -> None:
        gate = evaluate_gate({"a": {"score": 0.9, "error_rate": 0.05}}, self.THRESHOLDS, {})
        assert gate.passed

    def test_threshold_failures(self) -> None:
        gate = evaluate_gate({"a": {"score": 0.7, "error_rate": 0.2}}, self.THRESHOLDS, {})
        assert not gate.passed
        assert len(gate.failures) == 2

    def test_missing_metric_fails(self) -> None:
        gate = evaluate_gate({"a": {"score": 0.9}}, self.THRESHOLDS, {})
        assert any("missing" in f for f in gate.failures)

    def test_regression_against_baseline(self) -> None:
        metrics = {"a": {"score": 0.85, "error_rate": 0.09}}
        baseline = {"a.score": 0.95, "a.error_rate": 0.02}
        gate = evaluate_gate(metrics, self.THRESHOLDS, baseline)
        assert not gate.passed
        assert all("regressed" in f for f in gate.failures)
        assert len(gate.failures) == 2

    def test_regression_within_tolerance(self) -> None:
        metrics = {"a": {"score": 0.93, "error_rate": 0.04}}
        gate = evaluate_gate(metrics, self.THRESHOLDS, {"a.score": 0.95, "a.error_rate": 0.02})
        assert gate.passed


def snapshot(**overrides: object) -> DriftSnapshot:
    base: dict[str, object] = {
        "counts": {"documents": 50},
        "categorical": {"document_type": {"invoice": 25, "bank_statement": 25}},
        "histograms": {"document_length": [10, 20, 20, 0, 0, 0]},
        "scalars": {"review_rate": 0.1, "groundedness_mean": 0.95, "latency_p95_ms": 1000.0},
        "versions": {"models": ["bedrock:claude"], "prompts": ["rag@1.0.0"]},
        "samples": {"review_rate": 50, "groundedness_mean": 50, "latency_p95_ms": 50},
    }
    base.update(overrides)
    return DriftSnapshot.model_validate(base)


class TestDrift:
    def test_histogram_and_psi(self) -> None:
        assert histogram([1, 5, 15, 1000], [0, 10, 100, float("inf")]) == [2, 1, 1]
        assert psi([10, 10, 10], [10, 10, 10]) == 0.0
        assert psi([100, 0, 0], [0, 0, 100]) > 1.0
        assert psi({"a": 5, "b": 5}, {"a": 5, "b": 5}) == 0.0

    @pytest.fixture
    def monitor(self) -> DriftMonitor:
        thresholds = DriftThresholds(
            min_samples=5,
            rate_delta={"review_rate": 0.15, "groundedness_mean": 0.1},
            ratio={"latency_p95_ms": 1.5},
        )
        return DriftMonitor(None, None, None, None, None, None, thresholds)  # type: ignore[arg-type]

    def test_no_drift(self, monitor: DriftMonitor) -> None:
        report = monitor.compare(snapshot(), snapshot())
        assert report.status == "ok"
        assert report.alerts == []

    def test_review_rate_and_grounding_and_latency_alerts(self, monitor: DriftMonitor) -> None:
        current = snapshot(
            scalars={"review_rate": 0.4, "groundedness_mean": 0.7, "latency_p95_ms": 2000.0}
        )
        report = monitor.compare(current, snapshot())
        assert report.status == "alert"
        alerted = {m.name for m in report.metrics if m.status == "alert"}
        assert alerted == {"review_rate", "groundedness_mean", "latency_p95_ms"}

    def test_distribution_shift_alert(self, monitor: DriftMonitor) -> None:
        current = snapshot(categorical={"document_type": {"invoice": 48, "bank_statement": 2}})
        report = monitor.compare(current, snapshot())
        metric = next(m for m in report.metrics if m.name == "document_type_distribution")
        assert metric.status == "alert"

    def test_small_samples_are_not_judged(self, monitor: DriftMonitor) -> None:
        current = snapshot(
            categorical={"document_type": {"invoice": 2}},
            histograms={"document_length": [2, 0, 0, 0, 0, 0]},
            scalars={"review_rate": 1.0, "groundedness_mean": 0.1, "latency_p95_ms": 9000.0},
            samples={"review_rate": 2, "groundedness_mean": 2, "latency_p95_ms": 2},
        )
        report = monitor.compare(current, snapshot())
        assert report.status == "insufficient_data"
        assert report.alerts == []

    def test_new_model_version_is_flagged(self, monitor: DriftMonitor) -> None:
        current = snapshot(versions={"models": ["bedrock:claude-v2"], "prompts": ["rag@1.0.0"]})
        report = monitor.compare(current, snapshot())
        assert any("new versions" in a for a in report.alerts)

    def test_no_baseline(self, monitor: DriftMonitor) -> None:
        assert monitor.compare(snapshot(), None).status == "no_baseline"
