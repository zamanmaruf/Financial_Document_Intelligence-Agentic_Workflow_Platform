"""Input and output policy checks for the question-answering path."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.guardrails.injection import scan_for_injection

MAX_QUESTION_CHARS = 1000

_ADVICE_RE = re.compile(
    r"\b(you should (buy|sell|invest|hold)|we recommend (buying|selling|investing)|"
    r"guaranteed (return|profit)s?|risk[- ]free (return|investment))\b",
    re.I,
)


@dataclass
class QuestionCheck:
    allowed: bool
    reason: str | None = None
    patterns: list[str] = field(default_factory=list)


def check_question(question: str) -> QuestionCheck:
    q = question.strip()
    if not q:
        return QuestionCheck(False, "question is empty")
    if len(q) > MAX_QUESTION_CHARS:
        return QuestionCheck(False, f"question exceeds {MAX_QUESTION_CHARS} characters")
    scan = scan_for_injection(q)
    if scan.flagged:
        return QuestionCheck(False, "question blocked by prompt-injection guardrail", scan.patterns)
    return QuestionCheck(True)


def find_prohibited_claims(answer: str) -> list[str]:
    """Statements the platform must never make (investment advice / guarantees)."""
    return sorted({m.group(0).lower() for m in _ADVICE_RE.finditer(answer)})
