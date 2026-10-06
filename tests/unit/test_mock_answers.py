"""The offline engine's answer picker on everyday wording."""

from __future__ import annotations

import pytest

from app.providers.llm.mock_handlers import rag_answer_handler

INVOICE = "\n".join(
    [
        "ACME OFFICE SUPPLIES LTD",
        "INVOICE",
        "Invoice Number: INV-2025-0412",
        "Invoice Date: 2025-03-14",
        "Due Date: 2025-04-13",
        "Vendor: Acme Office Supplies Ltd",
        "Bill To: Northwind Traders Inc.",
        "Currency: USD",
        "Subtotal: 4,850.00",
        "Tax (8%): 388.00",
        "Amount Due: 5,238.00",
        "Payment terms: Net 30.",
    ]
)


def answer(question: str) -> str:
    out = rag_answer_handler(
        {"question": question, "context_chunks": [{"chunk_id": "c1", "text": INVOICE}]}
    )
    return str(out["answer"])


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Who sent this invoice?", "Vendor: Acme Office Supplies Ltd"),
        ("Who issued this invoice?", "Vendor: Acme Office Supplies Ltd"),
        ("Who is this invoice for?", "Bill To: Northwind Traders Inc."),
        ("Who was it sent to?", "Bill To: Northwind Traders Inc."),
        ("When was it issued?", "Invoice Date: 2025-03-14"),
        ("When is this invoice due?", "Due Date: 2025-04-13"),
        ("How much do I owe?", "Amount Due: 5,238.00"),
        ("What is the VAT?", "Tax (8%): 388.00"),
    ],
)
def test_everyday_questions_find_the_labelled_line(question: str, expected: str) -> None:
    assert answer(question) == expected


def test_unrelated_questions_are_still_refused() -> None:
    out = rag_answer_handler(
        {
            "question": "What is the CEO's favourite colour?",
            "context_chunks": [{"chunk_id": "c1", "text": INVOICE}],
        }
    )
    assert out["insufficient_evidence"] is True
