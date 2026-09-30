"""Quality gate: absolute thresholds + regression tolerance against a stored baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Thresholds:
    limits: dict[str, dict[str, float]]
    regression_metrics: list[str] = field(default_factory=list)
    tolerance: float = 0.03


@dataclass
class GateResult:
    passed: bool
    failures: list[str]
    checked: int


def load_thresholds(path: Path) -> Thresholds:
    data = yaml.safe_load(path.read_text()) or {}
    reg = data.get("regression", {}) or {}
    return Thresholds(
        limits=data.get("thresholds", {}) or {},
        regression_metrics=list(reg.get("metrics", []) or []),
        tolerance=float(reg.get("tolerance", 0.03)),
    )


def load_baseline(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {str(k): float(v) for k, v in data.get("metrics", {}).items()}


def lookup(metrics: dict[str, Any], dotted: str) -> float | None:
    node: Any = metrics
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return float(node) if isinstance(node, int | float) else None


def evaluate_gate(
    metrics: dict[str, Any], thresholds: Thresholds, baseline: dict[str, float]
) -> GateResult:
    failures: list[str] = []
    checked = 0
    for name, limit in thresholds.limits.items():
        value = lookup(metrics, name)
        checked += 1
        if value is None:
            failures.append(f"{name}: metric missing")
            continue
        if "min" in limit and value < float(limit["min"]):
            failures.append(f"{name}: {value:.4f} < min {float(limit['min']):.4f}")
        if "max" in limit and value > float(limit["max"]):
            failures.append(f"{name}: {value:.4f} > max {float(limit['max']):.4f}")
    for name in thresholds.regression_metrics:
        if name not in baseline:
            continue
        value = lookup(metrics, name)
        if value is None:
            continue
        checked += 1
        higher_is_better = "max" not in thresholds.limits.get(name, {})
        base = baseline[name]
        if higher_is_better and value < base - thresholds.tolerance:
            failures.append(_regression_msg(name, value, base, thresholds.tolerance))
        if not higher_is_better and value > base + thresholds.tolerance:
            failures.append(_regression_msg(name, value, base, thresholds.tolerance))
    return GateResult(passed=not failures, failures=failures, checked=checked)


def _regression_msg(name: str, value: float, base: float, tolerance: float) -> str:
    return f"{name}: regressed {value:.4f} vs baseline {base:.4f} (tolerance {tolerance})"


def baseline_snapshot(metrics: dict[str, Any], names: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in names:
        value = lookup(metrics, name)
        if value is not None:
            out[name] = value
    return out
