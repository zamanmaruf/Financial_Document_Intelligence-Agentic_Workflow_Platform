"""PII masking used before storage/indexing and in log redaction.

Pattern-based masking reduces exposure of common identifiers (account/card numbers, IBANs,
emails). It is best-effort: it will miss unusual formats and is not a substitute for access
control, encryption and data-minimisation.
"""

from __future__ import annotations

import re
from typing import Any

# Credential-like keys. Deliberately does not match token *counts* (input_tokens, tokens_estimated).
_SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|secret|password|passwd|authorization|credential|"
    r"(access|refresh|session|auth|bearer|id)[_-]?token|^token$)",
    re.I,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 8+ digits possibly separated by single spaces/dashes (account / card numbers); keep last 4.
# Monetary amounts are excluded because they contain ',' or '.' separators; identifiers such as
# "INV-2025-0412" are excluded by requiring no preceding word character or hyphen. A trailing
# sentence full stop still masks ("... 1234567890.") while decimals ("12345678.90") do not.
_ACCOUNT_RE = re.compile(r"(?<![\w.,-])(?:\d[ -]?){4,}(\d{4})(?![\d,]|\.\d)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")


def _mask_iban(match: re.Match[str]) -> str:
    compact = match.group(0).replace(" ", "")
    return f"****{compact[-4:]}"


def redact_text(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _IBAN_RE.sub(_mask_iban, text)
    return _ACCOUNT_RE.sub(lambda m: f"****{m.group(1)}", text)


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, v) for v in value]
    return value
