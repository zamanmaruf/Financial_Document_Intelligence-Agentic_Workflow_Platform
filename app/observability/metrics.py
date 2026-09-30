"""Metrics abstraction.

``MetricsRecorder`` is a tiny protocol (counters + histograms with labels). ``InMemoryMetrics``
powers the local ``/metrics`` endpoint (JSON and Prometheus text format). ``OpenTelemetryMetrics``
forwards to the OpenTelemetry API while keeping the in-memory view; exporting to CloudWatch,
Azure Application Insights or any OTLP backend is a deployment-time exporter choice, not a code
change.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from typing import Any, Protocol, runtime_checkable

Labels = dict[str, str]
_MAX_SAMPLES = 5000


@runtime_checkable
class MetricsRecorder(Protocol):
    def increment(self, name: str, value: float = 1.0, labels: Labels | None = None) -> None: ...

    def observe(self, name: str, value: float, labels: Labels | None = None) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...


def _key(labels: Labels | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((labels or {}).items()))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


class InMemoryMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
        self._hist: dict[str, dict[tuple[tuple[str, str], ...], deque[float]]] = defaultdict(dict)
        self._hist_totals: dict[str, dict[tuple[tuple[str, str], ...], tuple[int, float]]] = (
            defaultdict(dict)
        )

    def increment(self, name: str, value: float = 1.0, labels: Labels | None = None) -> None:
        k = _key(labels)
        with self._lock:
            self._counters[name][k] = self._counters[name].get(k, 0.0) + value

    def observe(self, name: str, value: float, labels: Labels | None = None) -> None:
        k = _key(labels)
        with self._lock:
            series = self._hist[name].setdefault(k, deque(maxlen=_MAX_SAMPLES))
            series.append(value)
            count, total = self._hist_totals[name].get(k, (0, 0.0))
            self._hist_totals[name][k] = (count + 1, total + value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = {
                name: [{"labels": dict(k), "value": v} for k, v in sorted(series.items())]
                for name, series in sorted(self._counters.items())
            }
            histograms: dict[str, Any] = {}
            for name, series_map in sorted(self._hist.items()):
                rows = []
                for k, samples in sorted(series_map.items()):
                    values = list(samples)
                    count, total = self._hist_totals[name][k]
                    rows.append(
                        {
                            "labels": dict(k),
                            "count": count,
                            "sum": round(total, 6),
                            "avg": round(total / count, 6) if count else 0.0,
                            "p50": round(percentile(values, 0.5), 6),
                            "p95": round(percentile(values, 0.95), 6),
                            "max": round(max(values), 6) if values else 0.0,
                        }
                    )
                histograms[name] = rows
        return {"counters": counters, "histograms": histograms}

    def prometheus_text(self) -> str:
        snap = self.snapshot()
        lines: list[str] = []

        def fmt_labels(labels: dict[str, str]) -> str:
            if not labels:
                return ""
            inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            return "{" + inner + "}"

        for name, rows in snap["counters"].items():
            metric = f"docintel_{name}" if name.endswith("_total") else f"docintel_{name}_total"
            lines.append(f"# TYPE {metric} counter")
            lines.extend(f"{metric}{fmt_labels(r['labels'])} {r['value']}" for r in rows)
        for name, rows in snap["histograms"].items():
            metric = f"docintel_{name}"
            lines.append(f"# TYPE {metric} summary")
            for r in rows:
                labels = r["labels"]
                for q in ("p50", "p95"):
                    ql = {**labels, "quantile": "0.5" if q == "p50" else "0.95"}
                    lines.append(f"{metric}{fmt_labels(ql)} {r[q]}")
                lines.append(f"{metric}_count{fmt_labels(labels)} {r['count']}")
                lines.append(f"{metric}_sum{fmt_labels(labels)} {r['sum']}")
        return "\n".join(lines) + "\n"


class OpenTelemetryMetrics(InMemoryMetrics):
    """Forwards to the OpenTelemetry metrics API and keeps the local in-memory view.

    Without a configured ``MeterProvider`` the OTel API is a no-op, so this is safe locally.
    """

    def __init__(self, meter_name: str = "fin-docintel") -> None:
        super().__init__()
        from opentelemetry import metrics as otel_metrics

        self._meter = otel_metrics.get_meter(meter_name)
        self._otel_counters: dict[str, Any] = {}
        self._otel_hists: dict[str, Any] = {}

    def increment(self, name: str, value: float = 1.0, labels: Labels | None = None) -> None:
        super().increment(name, value, labels)
        counter = self._otel_counters.get(name)
        if counter is None:
            counter = self._meter.create_counter(f"docintel.{name}")
            self._otel_counters[name] = counter
        counter.add(value, attributes=labels or {})

    def observe(self, name: str, value: float, labels: Labels | None = None) -> None:
        super().observe(name, value, labels)
        hist = self._otel_hists.get(name)
        if hist is None:
            hist = self._meter.create_histogram(f"docintel.{name}")
            self._otel_hists[name] = hist
        hist.record(value, attributes=labels or {})
