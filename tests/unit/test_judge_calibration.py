from __future__ import annotations

from app.core.text import extract_numbers
from app.evaluation.judge_calibration import (
    UNSUPPORTED_CLAIM,
    add_unsupported_claim,
    change_a_number,
    negate,
)

EVIDENCE = "Net income for FY2025 was $1,532,600. Total assets were $9,400,000 at 31 December 2025."


def test_changed_number_is_absent_from_the_evidence() -> None:
    answer = "Net income was $1,532,600."
    broken = change_a_number(answer, EVIDENCE)
    assert broken is not None and broken != answer
    assert broken.startswith("Net income was $1,532,6") and broken.endswith(".")
    assert not set(extract_numbers(broken)) & set(extract_numbers(EVIDENCE))


def test_changed_number_skips_single_digits_and_keeps_trailing_punctuation() -> None:
    broken = change_a_number("Step 1: assets were 9,400,000, per the note.", EVIDENCE)
    assert broken is not None
    assert broken.startswith("Step 1: assets were 9,400,00") and "0, per the note." not in broken
    assert broken.endswith(", per the note.")


def test_changed_number_needs_a_multi_digit_number() -> None:
    assert change_a_number("No figures here, see note 3.", EVIDENCE) is None


def test_negate_reverses_the_first_copula_once() -> None:
    assert negate("Net income was $1,532,600.", EVIDENCE) == "Net income was not $1,532,600."
    assert negate("Net income was not reported.", EVIDENCE) is None
    assert negate("Revenue rose sharply.", EVIDENCE) is None


def test_unsupported_claim_is_appended() -> None:
    assert add_unsupported_claim("Net income was $1,532,600. ", EVIDENCE) == (
        f"Net income was $1,532,600. {UNSUPPORTED_CLAIM}"
    )
