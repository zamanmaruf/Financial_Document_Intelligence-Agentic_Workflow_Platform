"""Deliberately broken answers for checking that a groundedness judge is not a rubber stamp.

Each function returns a corrupted copy of a correct, cited answer (or None when the answer has
nothing to corrupt). A useful judge should score the original as supported and the corrupted
copy as unsupported; ``scripts/judge_calibration.py`` measures both, next to the lexical check.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.core.text import extract_numbers

UNSUPPORTED_CLAIM = "The auditor later restated these figures after finding errors."

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_COPULA_RE = re.compile(r"\b(is|was|are|were)\b(?! not)")


def change_a_number(answer: str, evidence: str) -> str | None:
    """Change one digit of the first multi-digit number so it no longer matches the evidence."""
    ev_numbers = set(extract_numbers(evidence))
    for match in _NUMBER_RE.finditer(answer):
        raw = match.group(0).rstrip(",")
        digits = [i for i, ch in enumerate(raw) if ch.isdigit()]
        if len(digits) < 2:
            continue
        idx = digits[-1]
        for bump in (3, 4, 6, 7):
            new = raw[:idx] + str((int(raw[idx]) + bump) % 10) + raw[idx + 1 :]
            new_numbers = set(extract_numbers(new))
            if new_numbers and not new_numbers & ev_numbers:
                end = match.start() + len(raw)
                return answer[: match.start()] + new + answer[end:]
    return None


def negate(answer: str, evidence: str) -> str | None:
    """Insert "not" after the first is/was/are/were, reversing the claim."""
    match = _COPULA_RE.search(answer)
    if match is None:
        return None
    return answer[: match.end()] + " not" + answer[match.end() :]


def add_unsupported_claim(answer: str, evidence: str) -> str | None:
    """Append a plausible sentence that no source supports."""
    return f"{answer.rstrip()} {UNSUPPORTED_CLAIM}"


PERTURBATIONS: dict[str, Callable[[str, str], str | None]] = {
    "changed_number": change_a_number,
    "negated": negate,
    "unsupported_claim": add_unsupported_claim,
}
