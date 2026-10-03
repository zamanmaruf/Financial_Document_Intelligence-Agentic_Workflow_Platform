"""Deterministic text utilities shared by extraction, groundedness checks and evaluation."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "you",
        "your",
        "please",
        "tell",
        "me",
        "show",
        "give",
        "list",
        "much",
        "many",
        "any",
        "there",
        "been",
        "being",
        "can",
        "could",
        "would",
        "should",
        "about",
        "according",
        "document",
        "provided",
        "context",
    ]
)

_WS_RE = re.compile(r"\s+")
_DOT_LEADER_RE = re.compile(r"\.{2,}")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.,])[-(]?[$€£]?\s?\d(?:[\d,.]*\d)?\)?%?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n+")
_AMOUNT_RE = re.compile(r"\(?-?\s?[$€£]?\s?\d(?:[\d,.]*\d)?\)?")
_DOT_THOUSANDS_RE = re.compile(r"\d{1,3}(?:\.\d{3}){2,}")  # 1.234.567
_DECIMAL_COMMA_RE = re.compile(r"\d+,\d{1,2}")  # 12,5 / 1234,56


def normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def clean_line(text: str) -> str:
    """Collapse dot leaders and whitespace: 'Revenue ...... 1,000' -> 'Revenue 1,000'."""
    return normalize_ws(_DOT_LEADER_RE.sub(" ", text))


def _unify_separators(s: str) -> str:
    """Rewrite thousands/decimal separators to the '1234.56' form.

    Both separators present: the right-most one is the decimal mark ('1.234,56' and '1,234.56').
    Comma only: decimal when followed by 1-2 digits ('12,5'), otherwise thousands ('1,234').
    Dot only: thousands when grouped more than once ('1.234.567'); a single '1.234' stays a
    decimal because that reading is far more common in English-language documents.
    """
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            return s.replace(".", "").replace(",", ".")
        return s.replace(",", "")
    if "," in s:
        return s.replace(",", ".") if _DECIMAL_COMMA_RE.fullmatch(s) else s.replace(",", "")
    if _DOT_THOUSANDS_RE.fullmatch(s):
        return s.replace(".", "")
    return s


def normalize_number(raw: str) -> str | None:
    """Canonical string form of a number for comparison: '4,350,000.00' / '4.350.000,00' ->
    '4350000'."""
    s = raw.strip().replace("$", "").replace("€", "").replace("£", "").replace(" ", "")
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()%")
    if s.startswith("-"):
        negative = True
        s = s[1:]
    s = _unify_separators(s)
    if not s or not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    integer, _, fraction = s.partition(".")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    s = f"{integer}.{fraction}" if fraction else integer
    return f"-{s}" if negative and s != "0" else s


def all_numbers(text: str) -> list[str]:
    """Every number in ``text`` in canonical unsigned form ('(1,204,000)' -> '1204000')."""
    out: list[str] = []
    for match in _NUMBER_RE.finditer(text):
        norm = normalize_number(match.group(0))
        if norm is not None:
            out.append(norm.lstrip("-"))
    return out


def extract_numbers(text: str) -> list[str]:
    """All numbers in ``text`` in canonical form, excluding bare single digits (list markers)."""
    return [n for n in all_numbers(text) if len(n.replace(".", "")) >= 2]


def canonical_number(value: float) -> str | None:
    """Canonical unsigned form of a numeric value, comparable with ``all_numbers`` output."""
    return normalize_number(f"{abs(value):.6f}")


def parse_amount(text: str) -> tuple[float, str] | None:
    """First monetary amount in ``text`` -> (value, raw_match). Parentheses mean negative."""
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(0).strip()
        norm = normalize_number(raw)
        if norm is None:
            continue
        return float(norm), raw
    return None


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        norm = normalize_number(raw) if raw[0].isdigit() else None
        tokens.append(norm if norm is not None else _stem(raw.rstrip("%")))
    return tokens


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s and s.strip()]


def contains_normalized(haystack: str, needle: str) -> bool:
    """Case- and whitespace-insensitive containment (dot leaders ignored)."""
    return clean_line(needle).lower() in clean_line(haystack).lower()
