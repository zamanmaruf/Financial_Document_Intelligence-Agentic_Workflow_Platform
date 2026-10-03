"""Deterministic "simulated model" handlers used by ``MockLLMProvider``.

These are transparent rule-based engines, not machine-learned models:

* classification: weighted keyword matching over ``config/document_types.yaml``
* extraction: label-synonym line matching with typed value parsing
* rag answer: extractive selection of the best-overlapping line from the supplied context
* groundedness judge: lexical support ratio

They exist so the full pipeline (prompting, JSON parsing, schema validation, retries, HITL
routing, evaluation) can be exercised offline and in CI. Their quality is NOT representative of
a real LLM and every output they produce is tagged ``is_mock``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from app.core.registry import DocumentTypeRegistry
from app.core.text import (
    clean_line,
    content_tokens,
    extract_numbers,
    normalize_number,
    parse_amount,
    split_sentences,
)
from app.domain.enums import DocumentType
from app.extraction.schemas import FieldKind

MockHandler = Callable[[dict[str, Any]], dict[str, Any]]

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
_ISO_CURRENCY_RE = re.compile(r"\b(USD|EUR|GBP|CHF|JPY|CAD|AUD|SEK|NOK|DKK|SGD|HKD)\b")
_PERCENT_RE = re.compile(r"-?\d+(?:\.\d+)?\s?%")
_DIGITS_RE = re.compile(r"\d")
# Fields whose value may be printed only as an unlabelled heading on the first page.
_HEADING_KEYWORDS = {"bank_name": ("bank", "credit union", "building society")}


# --------------------------------------------------------------------------- classification


def make_classification_handler(registry: DocumentTypeRegistry) -> MockHandler:
    def handle(variables: dict[str, Any]) -> dict[str, Any]:
        text = str(variables.get("document_text", "")).lower()
        scores: dict[str, float] = {}
        matched: dict[str, list[str]] = {}
        for doc_type, cfg in registry.document_types.items():
            score = 0.0
            hits: list[str] = []
            for phrase, weight in cfg.keywords.items():
                count = len(re.findall(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", text))
                if count:
                    score += weight * min(count, 2)
                    hits.append(phrase)
            scores[doc_type.value] = score
            matched[doc_type.value] = hits

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        (top_type, top_score), (_, second_score) = ranked[0], ranked[1]
        if top_score < 6:
            return {
                "document_type": DocumentType.UNKNOWN.value,
                "confidence": 0.3,
                "reasoning_summary": "Too few indicative financial-document terms were found "
                "(rule-based mock classifier).",
            }
        confidence = round(top_score / (top_score + second_score + 2.0), 3)
        terms = ", ".join(f"'{t}'" for t in matched[top_type][:5])
        return {
            "document_type": top_type,
            "confidence": confidence,
            "reasoning_summary": f"Matched indicative terms {terms} (rule-based mock classifier).",
        }

    return handle


# --------------------------------------------------------------------------- extraction


def _label_regex(label: str) -> re.Pattern[str]:
    # label, optional parenthetical or rate ('VAT (21%)', 'VAT 19%'), then an explicit separator:
    # colon, '#', dot leaders or a wide column gap. The separator requirement avoids
    # 'Fund Manager' matching label 'fund'.
    return re.compile(
        rf"^\W*{re.escape(label)}\.?(?:\s*\([^)]*\)|\s+\d+(?:[.,]\d+)?\s?%)?"
        rf"\s*(?::|#|\.{{2,}}|\s{{2,}})\s*(?P<value>.+)$",
        re.IGNORECASE,
    )


def _mask_account(value: str) -> str | None:
    digits = "".join(_DIGITS_RE.findall(value))
    if len(digits) < 4:
        return None
    return f"****{digits[-4:]}"


def _parse_value(kind: FieldKind, value_text: str) -> tuple[Any, str] | None:
    value_text = clean_line(value_text)
    if not value_text:
        return None
    if kind == FieldKind.AMOUNT:
        parsed = parse_amount(value_text)
        return (parsed[0], parsed[1]) if parsed else None
    if kind == FieldKind.PERCENT:
        m = _PERCENT_RE.search(value_text)
        if not m:
            return None
        norm = normalize_number(m.group(0))
        return (float(norm), m.group(0)) if norm is not None else None
    if kind == FieldKind.CURRENCY:
        m = _ISO_CURRENCY_RE.search(value_text.upper())
        if m:
            return m.group(1), m.group(1)
        for sym, code in _CURRENCY_SYMBOLS.items():
            if sym in value_text:
                return code, sym
        return None
    if kind == FieldKind.MASKED_ACCOUNT:
        masked = _mask_account(value_text)
        return (masked, masked) if masked else None
    # text / date: take the value up to a wide column gap
    first_col = re.split(r"\s{3,}", value_text)[0].strip()
    return (first_col, first_col) if first_col else None


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.01, 1e-6 * max(abs(a), abs(b)))
    return str(a).strip().lower() == str(b).strip().lower()


def make_extraction_handler(registry: DocumentTypeRegistry) -> MockHandler:
    def handle(variables: dict[str, Any]) -> dict[str, Any]:
        doc_type = DocumentType(str(variables["document_type"]))
        cfg = registry.get(doc_type)
        pages: list[dict[str, Any]] = list(variables.get("pages", []))
        fields: list[dict[str, Any]] = list(variables.get("fields", []))
        out: dict[str, dict[str, Any]] = {}
        for field in fields:
            name = str(field["name"])
            kind = FieldKind(str(field["kind"]))
            labels = cfg.labels.get(name, []) if cfg else []
            ordered = sorted(labels, key=len, reverse=True)
            patterns = [(lbl, _label_regex(lbl)) for lbl in ordered]
            matches: list[dict[str, Any]] = []
            for page in pages:
                for line in str(page["text"]).splitlines():
                    for label, pattern in patterns:
                        m = pattern.match(line)
                        if not m:
                            continue
                        parsed = _parse_value(kind, m.group("value"))
                        if parsed is None:
                            break
                        value, raw = parsed
                        matches.append(
                            {
                                "value": value,
                                "raw_text": raw,
                                "page_number": page["page_number"],
                                "evidence_snippet": clean_line(line),
                                "canonical": label == (labels[0] if labels else label),
                            }
                        )
                        break
            if kind == FieldKind.CURRENCY and not matches:
                matches = _infer_currency(pages)
            if name in _HEADING_KEYWORDS and not matches:
                matches = _heading_match(pages, _HEADING_KEYWORDS[name])
            if not matches:
                out[name] = {"value": None, "confidence": 0.0}
                continue
            first = matches[0]
            distinct: list[Any] = [first["value"]]
            for other in matches[1:]:
                if not any(_values_equal(other["value"], d) for d in distinct):
                    distinct.append(other["value"])
            if len(distinct) > 1:
                confidence = 0.5
            elif first.get("inferred"):
                confidence = 0.7
            else:
                confidence = 0.95 if first["canonical"] else 0.88
            out[name] = {
                "value": first["value"],
                "raw_text": first["raw_text"],
                "page_number": first["page_number"],
                "evidence_snippet": first["evidence_snippet"],
                "confidence": confidence,
                "alternatives": distinct[1:],
            }
        return {"fields": out}

    return handle


def _heading_match(pages: list[dict[str, Any]], keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    if not pages:
        return []
    lines = [clean_line(line) for line in str(pages[0]["text"]).splitlines()]
    heading = next((line for line in lines if line), "")
    if not heading or not any(k in heading.lower() for k in keywords):
        return []
    return [
        {
            "value": heading,
            "raw_text": heading,
            "page_number": pages[0]["page_number"],
            "evidence_snippet": heading,
            "canonical": False,
        }
    ]


def _infer_currency(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for page in pages:
        for line in str(page["text"]).splitlines():
            m = _ISO_CURRENCY_RE.search(line)
            code = m.group(1) if m else None
            if code is None:
                code = next((c for s, c in _CURRENCY_SYMBOLS.items() if s in line), None)
            if code:
                return [
                    {
                        "value": code,
                        "raw_text": m.group(1) if m else code,
                        "page_number": page["page_number"],
                        "evidence_snippet": clean_line(line),
                        "canonical": False,
                        "inferred": True,
                    }
                ]
    return []


# --------------------------------------------------------------------------- RAG


INSUFFICIENT_ANSWER = "The provided documents do not contain enough information to answer this."
MIN_COVERAGE = 0.5


def rag_answer_handler(variables: dict[str, Any]) -> dict[str, Any]:
    """Pick the single context sentence that best covers the question.

    Question tokens are IDF-weighted over the context sentences (so a company name repeated in
    headers counts less than a distinctive term such as 'equity'), with a preference for
    sentences that contain a figure and against all-caps title lines. Coverage below half of the
    question weight is reported as insufficient evidence.
    """
    question_tokens = set(content_tokens(str(variables.get("question", ""))))
    chunks: list[dict[str, Any]] = list(variables.get("context_chunks", []))
    candidates: list[tuple[str, str, set[str]]] = []  # (sentence, chunk_id, tokens)
    for chunk in chunks:
        for line in str(chunk["text"]).splitlines():
            for sentence in split_sentences(clean_line(line)):
                tokens = set(content_tokens(sentence))
                if tokens:
                    candidates.append((sentence, str(chunk["chunk_id"]), tokens))
    if not candidates or not question_tokens:
        return {"answer": INSUFFICIENT_ANSWER, "cited_chunk_ids": [], "insufficient_evidence": True}

    n = len(candidates)
    df = {t: sum(1 for _, _, toks in candidates if t in toks) for t in question_tokens}
    weight = {t: math.log(1 + n / df[t]) if df[t] else math.log(1 + n) for t in question_tokens}
    total_weight = sum(weight.values())

    best: tuple[float, int, str, str] | None = None  # (score, -order, sentence, chunk_id)
    for order, (sentence, chunk_id, tokens) in enumerate(candidates):
        coverage = sum(weight[t] for t in question_tokens & tokens) / total_weight
        if coverage < MIN_COVERAGE:
            continue
        # financial questions usually ask for a figure; all-caps title lines are rarely answers
        has_figure = 0.25 if extract_numbers(sentence) else 0.0
        title_penalty = 0.15 if sentence.isupper() else 0.0
        score = coverage + has_figure - title_penalty + 0.01 / len(tokens)
        candidate = (score, -order, sentence, chunk_id)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return {"answer": INSUFFICIENT_ANSWER, "cited_chunk_ids": [], "insufficient_evidence": True}
    return {"answer": best[2], "cited_chunk_ids": [best[3]], "insufficient_evidence": False}


def groundedness_judge_handler(variables: dict[str, Any]) -> dict[str, Any]:
    answer_tokens = set(content_tokens(str(variables.get("answer", ""))))
    context_tokens = set(content_tokens(str(variables.get("context", ""))))
    if not answer_tokens:
        return {"score": 0.0, "verdict": "unsupported", "rationale": "Empty answer."}
    score = round(len(answer_tokens & context_tokens) / len(answer_tokens), 3)
    return {
        "score": score,
        "verdict": "supported" if score >= 0.8 else "unsupported",
        "rationale": "Lexical support ratio (mock judge).",
    }


def default_handlers(registry: DocumentTypeRegistry) -> dict[str, MockHandler]:
    return {
        "classification.document_type": make_classification_handler(registry),
        "extraction.financial_entities": make_extraction_handler(registry),
        "rag.grounded_answer": rag_answer_handler,
        "validation.groundedness_judge": groundedness_judge_handler,
    }
