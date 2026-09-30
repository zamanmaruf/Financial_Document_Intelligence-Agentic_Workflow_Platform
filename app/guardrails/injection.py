"""Heuristic prompt-injection detection for user questions and document content.

This is *awareness*, not prevention: pattern matching catches common phrasings of direct and
indirect (document-embedded) injection so they can be blocked, flagged and routed to review.
The primary defences are architectural: document text is always framed as untrusted data in
prompts, model outputs are schema-validated, answers must cite retrieved chunks, and the model
has no tools or side-effecting permissions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(previous|prior|above|earlier|all|any|system)\b"
            r"[^.\n]{0,20}\b(instructions?|prompts?|rules|guidelines|directions)\b",
            re.I,
        ),
    ),
    (
        "role_override",
        re.compile(r"\b(you are now|act as|pretend to be|from now on you|new persona)\b", re.I),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,30}"
            r"\b(system prompt|hidden prompt|your instructions|the prompt)\b",
            re.I,
        ),
    ),
    ("new_instructions", re.compile(r"\b(new|updated|additional) instructions?\s*:", re.I)),
    (
        "markup_injection",
        re.compile(r"</?\s*(system|assistant|context|document|instructions?)\s*>", re.I),
    ),
    (
        "payment_manipulation",
        re.compile(
            # may span a line break: document text is often wrapped
            r"\b(approve|authori[sz]e|release|wire|transfer)\b[^.]{0,40}"
            r"\b(payment|funds|invoice|transfer|money)\b"
            r"[^.]{0,40}\b(immediately|without (review|approval|verification)|to account)\b",
            re.I,
        ),
    ),
    (
        "suppress_review",
        re.compile(
            r"\b(do not|don't|never)\b[^.\n]{0,20}\b(flag|report|review|escalate|verify|mention)\b",
            re.I,
        ),
    ),
]


@dataclass(frozen=True)
class InjectionMatch:
    pattern: str
    snippet: str


@dataclass
class InjectionScanResult:
    matches: list[InjectionMatch] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.matches)

    @property
    def patterns(self) -> list[str]:
        return sorted({m.pattern for m in self.matches})


def scan_for_injection(text: str, max_matches: int = 10) -> InjectionScanResult:
    result = InjectionScanResult()
    for name, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            start, end = max(0, m.start() - 20), min(len(text), m.end() + 20)
            result.matches.append(InjectionMatch(name, " ".join(text[start:end].split())))
            if len(result.matches) >= max_matches:
                return result
    return result
