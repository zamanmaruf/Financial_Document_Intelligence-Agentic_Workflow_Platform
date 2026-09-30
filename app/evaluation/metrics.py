"""Pure, deterministic evaluation metric functions (no I/O, no model calls)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from app.core.text import contains_normalized, content_tokens, extract_numbers, normalize_ws

# --------------------------------------------------------------------------- classification


def classification_metrics(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] | None = None
) -> dict[str, Any]:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have equal length")
    labels = sorted(set(labels or []) | set(y_true) | set(y_pred))
    confusion: dict[str, dict[str, int]] = {t: dict.fromkeys(labels, 0) for t in labels}
    for t, p in zip(y_true, y_pred, strict=True):
        confusion[t][p] += 1
    per_class: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[t][label] for t in labels if t != label)
        fn = sum(confusion[label][p] for p in labels if p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }
    supported = [lbl for lbl in labels if per_class[lbl]["support"] > 0]
    n = len(y_true)
    accuracy = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p) / n if n else 0.0

    def macro(key: str) -> float:
        return (
            round(sum(per_class[lbl][key] for lbl in supported) / len(supported), 4)
            if supported
            else 0.0
        )

    return {
        "n": n,
        "accuracy": round(accuracy, 4),
        "macro_precision": macro("precision"),
        "macro_recall": macro("recall"),
        "macro_f1": macro("f1"),
        "per_class": per_class,
        "confusion_matrix": confusion,
    }


# --------------------------------------------------------------------------- extraction


def values_exact_match(expected: Any, predicted: Any) -> bool:
    if expected is None or predicted is None:
        return expected is None and predicted is None
    if isinstance(expected, float) and isinstance(predicted, float):
        return expected == predicted
    return str(expected) == str(predicted)


def values_normalized_match(expected: Any, predicted: Any, tolerance_ratio: float = 0.005) -> bool:
    """Tolerant match: case/whitespace-insensitive strings; sign-insensitive amounts within
    tolerance (presentation conventions such as parenthesised expenses vary)."""
    if expected is None or predicted is None:
        return expected is None and predicted is None
    if isinstance(expected, int | float) and isinstance(predicted, int | float):
        a, b = abs(float(expected)), abs(float(predicted))
        return abs(a - b) <= max(0.01, tolerance_ratio * max(a, b))
    return normalize_ws(str(expected)).casefold() == normalize_ws(str(predicted)).casefold()


def extraction_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """``items``: one per (document, field) with keys
    document_type, field, expected, predicted, validation_status."""
    present = [i for i in items if i["expected"] is not None]
    absent = [i for i in items if i["expected"] is None]
    predicted = [i for i in items if i["predicted"] is not None]

    exact = sum(values_exact_match(i["expected"], i["predicted"]) for i in present)
    normalized = sum(values_normalized_match(i["expected"], i["predicted"]) for i in present)
    field_correct = sum(values_normalized_match(i["expected"], i["predicted"]) for i in items)
    missing = sum(1 for i in present if i["predicted"] is None)
    hallucinated = sum(1 for i in absent if i["predicted"] is not None)
    invalid = sum(1 for i in predicted if i.get("validation_status") == "invalid")

    by_type: dict[str, list[bool]] = defaultdict(list)
    by_field: dict[str, list[bool]] = defaultdict(list)
    for i in items:
        ok = values_normalized_match(i["expected"], i["predicted"])
        by_type[i["document_type"]].append(ok)
        by_field[i["field"]].append(ok)

    def ratio(a: int, b: int) -> float:
        return round(a / b, 4) if b else 0.0

    return {
        "n_fields": len(items),
        "exact_match": ratio(exact, len(present)),
        "normalized_match": ratio(normalized, len(present)),
        "field_accuracy": ratio(field_correct, len(items)),
        "missing_field_rate": ratio(missing, len(present)),
        "hallucinated_field_rate": ratio(hallucinated, len(absent)),
        "invalid_value_rate": ratio(invalid, len(predicted)),
        "field_accuracy_by_document_type": {
            k: ratio(sum(v), len(v)) for k, v in sorted(by_type.items())
        },
        "field_accuracy_by_field": {k: ratio(sum(v), len(v)) for k, v in sorted(by_field.items())},
    }


# --------------------------------------------------------------------------- retrieval


def retrieval_query_metrics(relevance: list[bool], total_relevant: int, k: int) -> dict[str, float]:
    """``relevance``: relevance flags of the ranked retrieved list (length <= k)."""
    hits = sum(relevance)
    first = next((rank for rank, rel in enumerate(relevance, start=1) if rel), None)
    return {
        "precision_at_k": hits / k if k else 0.0,
        "recall_at_k": hits / total_relevant if total_relevant else 0.0,
        "hit": 1.0 if hits else 0.0,
        "reciprocal_rank": 1.0 / first if first else 0.0,
    }


def lexical_context_relevance(query: str, chunk_texts: list[str]) -> float:
    """Mean fraction of query content tokens present in each retrieved chunk (lexical proxy)."""
    q = set(content_tokens(query))
    if not q or not chunk_texts:
        return 0.0
    return sum(len(q & set(content_tokens(t))) / len(q) for t in chunk_texts) / len(chunk_texts)


def mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


# --------------------------------------------------------------------------- answers


def fact_present(fact: str, text: str) -> bool:
    """A fact matches if it appears textually or, for numbers, numerically."""
    if contains_normalized(text, fact):
        return True
    fact_numbers = extract_numbers(fact)
    return bool(fact_numbers) and set(fact_numbers) <= set(extract_numbers(text))


def answer_completeness(expected_facts: list[str], answer: str) -> float:
    if not expected_facts:
        return 1.0
    return sum(fact_present(f, answer) for f in expected_facts) / len(expected_facts)


def lexical_answer_relevance(question: str, answer: str) -> float:
    q = set(content_tokens(question))
    a = set(content_tokens(answer))
    if not q or not a:
        return 0.0
    return len(q & a) / len(q)
