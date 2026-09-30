"""Structured JSON logging with request/document/workflow context and PII redaction.

Policy: document text, questions and answers are never logged verbatim; log lengths/hashes
instead. The redaction filter is a second line of defence, not a guarantee.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.guardrails.pii import redact_text, redact_value

__all__ = ["configure_logging", "log_event", "redact_text", "redact_value"]

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
document_id_var: ContextVar[str | None] = ContextVar("document_id", default=None)
workflow_id_var: ContextVar[str | None] = ContextVar("workflow_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for key, var in (
            ("request_id", request_id_var),
            ("document_id", document_id_var),
            ("workflow_id", workflow_id_var),
        ):
            val = var.get()
            if val:
                payload[key] = val
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for k, v in fields.items():
                payload[k] = redact_value(k, v)
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = payload.get("error_type") or record.exc_info[0].__name__
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, sort_keys=True)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<7} {record.name}: {redact_text(record.getMessage())}"
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            kv = " ".join(f"{k}={redact_value(k, v)}" for k, v in fields.items())
            base = f"{base} | {kv}"
        return base


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else TextFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("chromadb", "httpx", "urllib3", "botocore", "opentelemetry"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})
