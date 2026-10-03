"""Deterministic business-rule validation of extracted entities.

Rules are plain functions so they are trivially unit-testable and auditable. They never modify
values; they only annotate entities and emit ``ValidationIssue``s that drive review routing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from app.domain.enums import DocumentType, Severity, ValidationStatus
from app.domain.models import ExtractedEntity, ExtractionResult, ValidationIssue
from app.extraction.schemas import FieldKind, field_specs
from app.guardrails.injection import scan_for_injection

INJECTED_EVIDENCE_RULE = "evidence_suspected_injection"

ISO_CURRENCIES = frozenset(
    [
        "USD",
        "EUR",
        "GBP",
        "CHF",
        "JPY",
        "CAD",
        "AUD",
        "SEK",
        "NOK",
        "DKK",
        "SGD",
        "HKD",
        "NZD",
        "CNY",
        "INR",
        "BRL",
        "MXN",
        "ZAR",
    ]
)
_MASKED_RE = re.compile(r"^\*{4}\d{4}$")

Rule = Callable[[ExtractionResult, float], list[ValidationIssue]]


def _amount(result: ExtractionResult, name: str) -> float | None:
    value = result.value(name)
    return value if isinstance(value, float) else None


def _close(a: float, b: float, tol_ratio: float) -> bool:
    return abs(a - b) <= max(1.0, tol_ratio * max(abs(a), abs(b)))


def check_balance_sheet(result: ExtractionResult, tol: float) -> list[ValidationIssue]:
    assets = _amount(result, "total_assets")
    liabilities = _amount(result, "total_liabilities")
    equity = _amount(result, "shareholders_equity")
    if assets is None or liabilities is None or equity is None:
        return []
    if _close(assets, liabilities + equity, tol):
        return []
    return [
        ValidationIssue(
            rule="balance_sheet_identity",
            severity=Severity.ERROR,
            message=f"total_assets ({assets:,.2f}) != total_liabilities + shareholders_equity "
            f"({liabilities + equity:,.2f})",
            fields=["total_assets", "total_liabilities", "shareholders_equity"],
        )
    ]


def check_invoice(result: ExtractionResult, tol: float) -> list[ValidationIssue]:
    subtotal, tax, due = (_amount(result, n) for n in ("subtotal", "tax", "amount_due"))
    if subtotal is None or tax is None or due is None:
        return []
    if _close(subtotal + tax, due, tol):
        return []
    return [
        ValidationIssue(
            rule="invoice_total",
            severity=Severity.ERROR,
            message=f"subtotal + tax ({subtotal + tax:,.2f}) != amount_due ({due:,.2f})",
            fields=["subtotal", "tax", "amount_due"],
        )
    ]


def check_income_statement(result: ExtractionResult, tol: float) -> list[ValidationIssue]:
    revenue = _amount(result, "revenue")
    opex = _amount(result, "operating_expenses")
    op_income = _amount(result, "operating_income")
    issues: list[ValidationIssue] = []
    if revenue is not None and opex is not None and op_income is not None:
        # Operating income = revenue - cost of revenue - opex; without cost of revenue we can only
        # assert the upper bound. abs(): expenses are often printed in parentheses (negative).
        ceiling = revenue - abs(opex)
        if op_income > ceiling + max(1.0, tol * abs(revenue)):
            issues.append(
                ValidationIssue(
                    rule="income_statement_operating_income",
                    severity=Severity.ERROR,
                    message=f"operating_income ({op_income:,.2f}) exceeds revenue - "
                    f"operating_expenses ({ceiling:,.2f})",
                    fields=["revenue", "operating_expenses", "operating_income"],
                )
            )
    net = _amount(result, "net_income")
    if revenue is not None and net is not None and net > revenue:
        issues.append(
            ValidationIssue(
                rule="income_statement_net_le_revenue",
                severity=Severity.ERROR,
                message="net_income exceeds revenue",
                fields=["net_income", "revenue"],
            )
        )
    return issues


def check_bank_statement(result: ExtractionResult, tol: float) -> list[ValidationIssue]:
    opening, credits, debits, closing = (
        _amount(result, n)
        for n in ("opening_balance", "total_credits", "total_debits", "closing_balance")
    )
    if None in (opening, credits, debits, closing):
        return []
    assert opening is not None and credits is not None and debits is not None
    assert closing is not None
    expected = opening + credits - abs(debits)
    if _close(expected, closing, tol):
        return []
    return [
        ValidationIssue(
            rule="bank_statement_reconciliation",
            severity=Severity.ERROR,
            message=f"opening + credits - debits ({expected:,.2f}) != closing ({closing:,.2f})",
            fields=["opening_balance", "total_credits", "total_debits", "closing_balance"],
        )
    ]


def check_fund_summary(result: ExtractionResult, tol: float) -> list[ValidationIssue]:
    fee = result.value("management_fee_pct")
    if isinstance(fee, float) and not 0.0 <= fee <= 5.0:
        return [
            ValidationIssue(
                rule="fund_fee_range",
                severity=Severity.WARNING,
                message=f"management fee {fee}% outside plausible range 0-5%",
                fields=["management_fee_pct"],
            )
        ]
    return []


CROSS_FIELD_RULES: dict[DocumentType, list[Rule]] = {
    DocumentType.BALANCE_SHEET: [check_balance_sheet],
    DocumentType.INVOICE: [check_invoice],
    DocumentType.INCOME_STATEMENT: [check_income_statement],
    DocumentType.BANK_STATEMENT: [check_bank_statement],
    DocumentType.FUND_SUMMARY: [check_fund_summary],
}

_DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y")


def _plausible_date(value: str) -> bool:
    v = value.strip()
    if re.search(r"(19|20)\d{2}", v):  # periods like 'FY2024', 'Q3 2024', 'Jan-Mar 2025'
        return True
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(v, fmt)
            return True
        except ValueError:
            continue
    return False


def validate_field(entity: ExtractedEntity, kind: FieldKind) -> list[str]:
    """Per-field value checks. Returns messages; empty means valid."""
    value = entity.value
    if value is None:
        return []
    msgs: list[str] = []
    if kind == FieldKind.CURRENCY and str(value).upper() not in ISO_CURRENCIES:
        msgs.append(f"'{value}' is not a recognised ISO 4217 currency code")
    elif kind == FieldKind.MASKED_ACCOUNT and not _MASKED_RE.fullmatch(str(value)):
        msgs.append("account number is not masked to the last 4 digits")
    elif kind == FieldKind.DATE and not _plausible_date(str(value)):
        msgs.append(f"'{value}' is not a recognisable date or period")
    elif kind == FieldKind.PERCENT and isinstance(value, float) and not -100.0 <= value <= 1000.0:
        msgs.append(f"percentage {value} out of range")
    elif kind == FieldKind.AMOUNT and not isinstance(value, float):
        msgs.append("amount is not numeric")
    return msgs


def validate_extraction(result: ExtractionResult, tolerance_ratio: float) -> list[ValidationIssue]:
    """Annotate entities in place and return all validation issues."""
    issues: list[ValidationIssue] = []
    specs = {s.name: s for s in field_specs(result.document_type)}
    for entity in result.entities:
        spec = specs.get(entity.name)
        if spec is None:
            continue
        if entity.value is None:
            entity.validation_status = ValidationStatus.MISSING
            if spec.required:
                issues.append(
                    ValidationIssue(
                        rule="required_field",
                        severity=Severity.ERROR,
                        message=f"required field '{entity.name}' is missing",
                        fields=[entity.name],
                    )
                )
            continue
        msgs = validate_field(entity, spec.kind)
        if entity.evidence is not None and scan_for_injection(entity.evidence.snippet).flagged:
            # A value sourced from text that tries to instruct the model is never trusted, even
            # when that text is genuinely in the document (so the evidence "verifies").
            entity.validation_status = ValidationStatus.INVALID
            entity.messages.append("evidence is text flagged as a suspected prompt injection")
            issues.append(
                ValidationIssue(
                    rule=INJECTED_EVIDENCE_RULE,
                    severity=Severity.ERROR,
                    message=f"'{entity.name}' was taken from text flagged as a suspected "
                    "prompt injection",
                    fields=[entity.name],
                )
            )
        elif msgs:
            entity.validation_status = ValidationStatus.INVALID
            entity.messages.extend(msgs)
            issues.append(
                ValidationIssue(
                    rule="field_format",
                    severity=Severity.ERROR,
                    message="; ".join(msgs),
                    fields=[entity.name],
                )
            )
        elif entity.alternatives:
            entity.validation_status = ValidationStatus.CONFLICT
            issues.append(
                ValidationIssue(
                    rule="conflicting_values",
                    severity=Severity.ERROR,
                    message=f"'{entity.name}' has conflicting values in the document: "
                    f"{[entity.value, *entity.alternatives]}",
                    fields=[entity.name],
                )
            )
        elif entity.evidence is None or not entity.evidence.verified:
            entity.validation_status = ValidationStatus.UNVERIFIED
            issues.append(
                ValidationIssue(
                    rule="evidence_not_found",
                    severity=Severity.WARNING,
                    message=f"evidence for '{entity.name}' could not be located in the source text",
                    fields=[entity.name],
                )
            )
        else:
            entity.validation_status = ValidationStatus.VALID

    for rule in CROSS_FIELD_RULES.get(result.document_type, []):
        rule_issues = rule(result, tolerance_ratio)
        for issue in rule_issues:
            for name in issue.fields:
                ent = result.entity(name)
                if ent is not None and ent.validation_status == ValidationStatus.VALID:
                    ent.validation_status = ValidationStatus.INVALID
                    ent.messages.append(issue.message)
        issues.extend(rule_issues)
    return issues
