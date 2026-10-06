"""Scores for comparing OCR engines against the known text of a synthetic scan."""

from __future__ import annotations

from typing import Any

from app.core.text import all_numbers, canonical_number, contains_normalized, normalize_ws


def normalize_ocr_text(text: str) -> str:
    """One line per printed line, inner whitespace collapsed, blank lines dropped."""
    return "\n".join(normalize_ws(line) for line in text.splitlines() if line.strip())


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (insertions, deletions and substitutions all cost 1)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Edit distance over the normalised texts, divided by the reference length."""
    ref, hyp = normalize_ocr_text(reference), normalize_ocr_text(hypothesis)
    return edit_distance(ref, hyp) / max(1, len(ref))


def number_scores(reference: str, hypothesis: str) -> dict[str, Any]:
    """How many of the printed numbers were read exactly, and which numbers were made up.

    Numbers are compared in canonical form, so '1,080.00' and '1080' match. A misread digit
    shows up twice: the true number is missed and a wrong one is spurious.
    """
    ref, hyp = set(all_numbers(reference)), set(all_numbers(hypothesis))
    found = ref & hyp
    return {
        "numbers_total": len(ref),
        "numbers_read_exactly": len(found),
        "number_recall": len(found) / len(ref) if ref else 1.0,
        "missed_numbers": sorted(ref - hyp),
        "spurious_numbers": sorted(hyp - ref),
    }


def field_value_present(value: Any, text: str) -> bool:
    """Whether an expected field value appears in the OCR text (numbers in canonical form)."""
    if value is None:
        return True
    if isinstance(value, bool):
        return contains_normalized(text, str(value))
    if isinstance(value, int | float):
        canonical = canonical_number(float(value))
        return canonical is not None and canonical in set(all_numbers(text))
    if isinstance(value, str) and value.startswith("*"):  # masked account number: '****3016'
        suffix = value.lstrip("*")
        return any(n.endswith(suffix) for n in all_numbers(text))
    return contains_normalized(text, str(value))


def field_scores(expected_fields: dict[str, Any], hypothesis: str) -> dict[str, Any]:
    """Share of the document's expected field values that can be found in the OCR text.

    This measures whether the OCR output still contains each value, not whether a model then
    extracts it correctly.
    """
    missing = [
        name
        for name, value in expected_fields.items()
        if not field_value_present(value, hypothesis)
    ]
    total = len(expected_fields)
    return {
        "fields_total": total,
        "fields_found": total - len(missing),
        "field_recall": (total - len(missing)) / total if total else 1.0,
        "fields_missing": missing,
    }
