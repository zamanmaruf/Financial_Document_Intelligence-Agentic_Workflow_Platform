"""Document-specific extraction schemas.

Each supported document type has a typed Pydantic model. These models are the single source of
truth for:

* which fields are extracted for a type (and their descriptions, injected into prompts),
* the value type of each field (used to validate/coerce model output),
* which fields are required (``json_schema_extra={"required": True}``).

To add a new document type: add a ``DocumentType`` member, a schema here, keywords + label
synonyms in ``config/document_types.yaml``, validation rules (optional) and ground truth.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DocumentType


class FieldKind(StrEnum):
    TEXT = "text"
    AMOUNT = "amount"
    PERCENT = "percent"
    DATE = "date"
    CURRENCY = "currency"
    MASKED_ACCOUNT = "masked_account"


def _f(description: str, kind: FieldKind, required: bool = False) -> Any:
    return Field(
        default=None,
        description=description,
        json_schema_extra={"kind": kind.value, "required": required},
    )


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncomeStatementFields(_Schema):
    company_name: str | None = _f("Legal name of the reporting company", FieldKind.TEXT, True)
    reporting_period: str | None = _f("Period covered, e.g. 'FY2024'", FieldKind.DATE, True)
    currency: str | None = _f("ISO 4217 currency code", FieldKind.CURRENCY, True)
    revenue: float | None = _f("Total revenue for the period", FieldKind.AMOUNT, True)
    operating_expenses: float | None = _f("Total operating expenses", FieldKind.AMOUNT)
    operating_income: float | None = _f("Operating income / EBIT", FieldKind.AMOUNT)
    net_income: float | None = _f("Net income (profit) for the period", FieldKind.AMOUNT, True)


class BalanceSheetFields(_Schema):
    company_name: str | None = _f("Legal name of the reporting company", FieldKind.TEXT, True)
    reporting_period: str | None = _f("Balance sheet date", FieldKind.DATE, True)
    currency: str | None = _f("ISO 4217 currency code", FieldKind.CURRENCY, True)
    cash: float | None = _f("Cash and cash equivalents", FieldKind.AMOUNT)
    total_assets: float | None = _f("Total assets", FieldKind.AMOUNT, True)
    total_liabilities: float | None = _f("Total liabilities", FieldKind.AMOUNT, True)
    shareholders_equity: float | None = _f("Total shareholders' equity", FieldKind.AMOUNT, True)


class InvoiceFields(_Schema):
    invoice_number: str | None = _f("Invoice identifier", FieldKind.TEXT, True)
    invoice_date: str | None = _f("Invoice issue date", FieldKind.DATE, True)
    vendor: str | None = _f("Issuing vendor / supplier", FieldKind.TEXT, True)
    customer: str | None = _f("Billed customer", FieldKind.TEXT)
    currency: str | None = _f("ISO 4217 currency code", FieldKind.CURRENCY)
    subtotal: float | None = _f("Amount before tax", FieldKind.AMOUNT)
    tax: float | None = _f("Tax / VAT amount", FieldKind.AMOUNT)
    amount_due: float | None = _f("Total amount due", FieldKind.AMOUNT, True)


class BankStatementFields(_Schema):
    bank_name: str | None = _f(
        "Issuing bank or credit union (may appear only as the document heading)", FieldKind.TEXT
    )
    account_holder: str | None = _f("Account holder name", FieldKind.TEXT)
    account_number_masked: str | None = _f(
        "Account number, masked to last 4 digits", FieldKind.MASKED_ACCOUNT, True
    )
    statement_period: str | None = _f("Statement period", FieldKind.DATE, True)
    currency: str | None = _f("ISO 4217 currency code", FieldKind.CURRENCY)
    opening_balance: float | None = _f("Opening balance", FieldKind.AMOUNT, True)
    total_credits: float | None = _f("Sum of deposits / credits", FieldKind.AMOUNT)
    total_debits: float | None = _f("Sum of withdrawals / debits", FieldKind.AMOUNT)
    closing_balance: float | None = _f("Closing balance", FieldKind.AMOUNT, True)


class FundSummaryFields(_Schema):
    fund_name: str | None = _f("Name of the fund", FieldKind.TEXT, True)
    reporting_period: str | None = _f("Reporting period / as-of date", FieldKind.DATE, True)
    currency: str | None = _f("Base currency (ISO 4217)", FieldKind.CURRENCY)
    net_asset_value: float | None = _f("Total net asset value (AUM)", FieldKind.AMOUNT, True)
    nav_per_share: float | None = _f("NAV per share / unit", FieldKind.AMOUNT)
    ytd_return_pct: float | None = _f("Year-to-date return in percent", FieldKind.PERCENT)
    management_fee_pct: float | None = _f("Annual management fee in percent", FieldKind.PERCENT)


SCHEMAS: dict[DocumentType, type[_Schema]] = {
    DocumentType.INCOME_STATEMENT: IncomeStatementFields,
    DocumentType.BALANCE_SHEET: BalanceSheetFields,
    DocumentType.INVOICE: InvoiceFields,
    DocumentType.BANK_STATEMENT: BankStatementFields,
    DocumentType.FUND_SUMMARY: FundSummaryFields,
}


class FieldSpec(BaseModel):
    name: str
    description: str
    kind: FieldKind
    required: bool


def field_specs(document_type: DocumentType) -> list[FieldSpec]:
    schema = SCHEMAS.get(document_type)
    if schema is None:
        return []
    specs: list[FieldSpec] = []
    for name, info in schema.model_fields.items():
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        specs.append(
            FieldSpec(
                name=name,
                description=info.description or name,
                kind=FieldKind(str(extra.get("kind", FieldKind.TEXT.value))),
                required=bool(extra.get("required", False)),
            )
        )
    return specs
