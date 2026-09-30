"""Deterministic groundedness check for generated answers.

A sentence is *supported* when (1) every number in it appears in the cited evidence and (2) at
least ``token_support_threshold`` of its content tokens appear in the cited evidence. This is a
conservative lexical check: it catches invented figures reliably but can penalise legitimate
paraphrase (e.g. "4.35 million" vs "4,350,000"). It is combined with retrieval strength into the
answer confidence and complemented in evaluation by an optional LLM judge.
"""

from __future__ import annotations

from app.core.text import content_tokens, extract_numbers, split_sentences
from app.domain.models import GroundednessReport


def check_groundedness(
    answer: str, evidence_texts: list[str], token_support_threshold: float = 0.6
) -> GroundednessReport:
    evidence = "\n".join(evidence_texts)
    ev_tokens = set(content_tokens(evidence))
    ev_numbers = set(extract_numbers(evidence))
    sentences = [s for s in split_sentences(answer) if content_tokens(s)]
    if not sentences:
        return GroundednessReport(score=0.0, total_sentences=0, supported_sentences=0)

    supported = 0
    unsupported_sentences: list[str] = []
    unsupported_numbers: list[str] = []
    for sentence in sentences:
        numbers = extract_numbers(sentence)
        missing = [n for n in numbers if n not in ev_numbers]
        tokens = content_tokens(sentence)
        support = sum(1 for t in tokens if t in ev_tokens) / len(tokens)
        if not missing and support >= token_support_threshold:
            supported += 1
        else:
            unsupported_sentences.append(sentence)
            unsupported_numbers.extend(missing)
    return GroundednessReport(
        score=round(supported / len(sentences), 4),
        total_sentences=len(sentences),
        supported_sentences=supported,
        unsupported_sentences=unsupported_sentences,
        unsupported_numbers=sorted(set(unsupported_numbers)),
    )
