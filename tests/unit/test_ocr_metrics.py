from __future__ import annotations

import pytest

from app.evaluation.ocr_metrics import (
    character_error_rate,
    edit_distance,
    field_scores,
    field_value_present,
    normalize_ocr_text,
    number_scores,
)

REFERENCE = "INVOICE\n\nInvoice Number: LP-5520\nAmount Due: 2,808.00\nTax: 208.00"


class TestCharacterErrorRate:
    @pytest.mark.parametrize(
        ("a", "b", "distance"),
        [("", "", 0), ("abc", "", 3), ("kitten", "sitting", 3), ("flaw", "lawn", 2)],
    )
    def test_edit_distance(self, a: str, b: str, distance: int) -> None:
        assert edit_distance(a, b) == distance == edit_distance(b, a)

    def test_layout_whitespace_is_not_an_error(self) -> None:
        spaced = "  INVOICE \nInvoice   Number: LP-5520\n\nAmount Due: 2,808.00\nTax: 208.00\n"
        assert normalize_ocr_text(spaced) == normalize_ocr_text(REFERENCE)
        assert character_error_rate(REFERENCE, spaced) == 0.0

    def test_misread_characters_count(self) -> None:
        misread = REFERENCE.replace("2,808.00", "2,803.00").replace("Tax", "Tux")
        ref_len = len(normalize_ocr_text(REFERENCE))
        assert character_error_rate(REFERENCE, misread) == pytest.approx(2 / ref_len)
        assert character_error_rate(REFERENCE, "") == 1.0


class TestNumberScores:
    def test_misread_digit_is_missed_and_invented(self) -> None:
        scores = number_scores(REFERENCE, REFERENCE.replace("2,808.00", "2,803.00"))
        assert scores["numbers_total"] == 3  # 5520, 2808, 208
        assert scores["numbers_read_exactly"] == 2
        assert scores["missed_numbers"] == ["2808"]
        assert scores["spurious_numbers"] == ["2803"]

    def test_formatting_differences_still_match(self) -> None:
        reformatted = "Invoice Number LP-5520 Amount Due 2808 Tax 208.0"
        assert number_scores(REFERENCE, reformatted)["number_recall"] == 1.0


class TestFieldScores:
    def test_values_are_matched_by_type(self) -> None:
        assert field_value_present(2808.0, "Amount Due: 2,808.00")
        assert not field_value_present(2808.0, "Amount Due: 2,803.00")
        assert field_value_present("Litware Printing Co", "vendor: LITWARE  Printing Co")
        assert field_value_present("****3016", "Account Number: 6650 2214 7789 3016")
        assert not field_value_present("****3016", "Account Number: 6650 2214 7789 3018")
        assert field_value_present(None, "")

    def test_recall_and_missing_fields(self) -> None:
        scores = field_scores(
            {"invoice_number": "LP-5520", "amount_due": 2808.0, "tax": 999.0}, REFERENCE
        )
        assert scores["fields_found"] == 2
        assert scores["field_recall"] == pytest.approx(2 / 3)
        assert scores["fields_missing"] == ["tax"]
