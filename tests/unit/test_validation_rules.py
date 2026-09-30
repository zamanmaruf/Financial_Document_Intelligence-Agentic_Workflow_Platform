from __future__ import annotations

from typing import Any

import pytest

from app.domain.enums import DocumentType, ValidationStatus
from app.domain.models import Evidence, ExtractedEntity, ExtractionResult
from app.extraction.schemas import FieldKind
from app.extraction.service import coerce_field_value
from app.extraction.validation import validate_extraction, validate_field

TOL = 0.005


def result(
    doc_type: DocumentType,
    values: dict[str, Any],
    verified: bool = True,
    alternatives: dict[str, list[Any]] | None = None,
) -> ExtractionResult:
    entities = [
        ExtractedEntity(
            name=name,
            value=value,
            raw_text=str(value) if value is not None else None,
            evidence=Evidence(page_number=1, snippet=f"{name}: {value}", verified=verified)
            if value is not None
            else None,
            confidence=0.95 if value is not None else 0.0,
            alternatives=(alternatives or {}).get(name, []),
        )
        for name, value in values.items()
    ]
    return ExtractionResult(
        extraction_id="ext_1",
        document_id="doc_1",
        document_type=doc_type,
        entities=entities,
        overall_confidence=0.95,
        provider="mock",
        model_name="m",
        prompt_version="1.0.0",
    )


def rules(res: ExtractionResult) -> set[str]:
    return {i.rule for i in validate_extraction(res, TOL)}


BALANCE_OK = {
    "company_name": "Northwind",
    "reporting_period": "Dec 31, 2024",
    "currency": "USD",
    "total_assets": 1000.0,
    "total_liabilities": 600.0,
    "shareholders_equity": 400.0,
}


class TestCrossFieldRules:
    def test_balance_sheet_identity_holds(self) -> None:
        assert "balance_sheet_identity" not in rules(result(DocumentType.BALANCE_SHEET, BALANCE_OK))

    def test_balance_sheet_identity_violation(self) -> None:
        bad = {**BALANCE_OK, "shareholders_equity": 300.0}
        res = result(DocumentType.BALANCE_SHEET, bad)
        assert "balance_sheet_identity" in rules(res)

    def test_identity_within_tolerance(self) -> None:
        near = {**BALANCE_OK, "shareholders_equity": 401.0}  # 0.1% off
        assert "balance_sheet_identity" not in rules(result(DocumentType.BALANCE_SHEET, near))

    def test_invoice_total(self) -> None:
        base = {
            "invoice_number": "INV-1",
            "vendor": "A",
            "currency": "USD",
            "subtotal": 100.0,
            "tax": 8.0,
            "amount_due": 108.0,
        }
        assert "invoice_total" not in rules(result(DocumentType.INVOICE, base))
        assert "invoice_total" in rules(result(DocumentType.INVOICE, {**base, "amount_due": 120.0}))

    def test_bank_reconciliation_with_negative_debits(self) -> None:
        base = {
            "account_holder": "X",
            "account_number": "****1234",
            "currency": "USD",
            "statement_period": "March 2025",
            "opening_balance": 1000.0,
            "total_credits": 500.0,
            "total_debits": -200.0,
            "closing_balance": 1300.0,
        }
        assert "bank_statement_reconciliation" not in rules(
            result(DocumentType.BANK_STATEMENT, base)
        )
        broken = {**base, "closing_balance": 1500.0}
        assert "bank_statement_reconciliation" in rules(result(DocumentType.BANK_STATEMENT, broken))


class TestFieldRules:
    def test_missing_required_field(self) -> None:
        values = {**BALANCE_OK, "currency": None}
        res = result(DocumentType.BALANCE_SHEET, values)
        assert "required_field" in rules(res)
        assert res.entity("currency") is not None
        assert res.entity("currency").validation_status == ValidationStatus.MISSING  # type: ignore[union-attr]

    def test_conflicting_values(self) -> None:
        res = result(
            DocumentType.BALANCE_SHEET, BALANCE_OK, alternatives={"total_assets": [1100.0]}
        )
        assert "conflicting_values" in rules(res)
        assert res.entity("total_assets").validation_status == ValidationStatus.CONFLICT  # type: ignore[union-attr]

    def test_unverified_evidence(self) -> None:
        res = result(DocumentType.BALANCE_SHEET, BALANCE_OK, verified=False)
        assert "evidence_not_found" in rules(res)

    @pytest.mark.parametrize(
        ("kind", "value", "ok"),
        [
            (FieldKind.CURRENCY, "USD", True),
            (FieldKind.CURRENCY, "XYZ", False),
            (FieldKind.PERCENT, 0.75, True),
            (FieldKind.PERCENT, 2500.0, False),
            (FieldKind.MASKED_ACCOUNT, "****1234", True),
            (FieldKind.MASKED_ACCOUNT, "1234567890", False),
            (FieldKind.DATE, "2025-03-14", True),
        ],
    )
    def test_field_formats(self, kind: FieldKind, value: Any, ok: bool) -> None:
        messages = validate_field(ExtractedEntity(name="f", value=value), kind)
        assert (not messages) is ok


class TestCoercion:
    def test_amount_coercion(self) -> None:
        assert coerce_field_value(FieldKind.AMOUNT, "$1,234.50") == pytest.approx(1234.5)
        assert coerce_field_value(FieldKind.AMOUNT, "(500)") == pytest.approx(-500.0)

    def test_currency_and_account(self) -> None:
        assert coerce_field_value(FieldKind.CURRENCY, "usd") == "USD"
        assert coerce_field_value(FieldKind.MASKED_ACCOUNT, "1234567890") == "****7890"
