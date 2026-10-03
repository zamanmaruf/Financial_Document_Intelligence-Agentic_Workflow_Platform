"""Test helpers shared by unit, integration and e2e tests."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from app.core.config import LLMProviderName, Settings, VectorStoreName
from app.core.resilience import RetryPolicy
from app.domain.models import Document, WorkflowState
from app.services.container import Container

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDFS = ROOT / "sample_data" / "pdfs"
GROUND_TRUTH: dict[str, Any] = json.loads((ROOT / "sample_data" / "ground_truth.json").read_text())

NO_RETRY_DELAY = RetryPolicy(max_retries=2, backoff_s=0.0)


def make_settings(data_dir: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "data_dir": data_dir,
        # a developer's local web/dist build must not change what tests see at /
        "site_dir": data_dir / "no-site",
        "llm_provider": LLMProviderName.MOCK,
        "vector_store": VectorStoreName.MEMORY,
        "llm_retry_backoff_s": 0.0,
        "log_json": False,
        "log_level": "WARNING",
    }
    values.update(overrides)
    # _env_file=None keeps a developer's local .env from leaking into tests
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def sample_pdf(name: str) -> bytes:
    return (SAMPLE_PDFS / name).read_bytes()


def make_pdf(pages: list[str]) -> bytes:
    """Render simple text pages to a PDF (reportlab is a dev dependency)."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=True)
    for page in pages:
        text = c.beginText(50, 740)
        text.setFont("Courier", 10)
        for line in page.splitlines():
            text.textLine(line)
        c.drawText(text)
        c.showPage()
    c.save()
    return buf.getvalue()


def ingest(c: Container, name: str, data: bytes | None = None) -> Document:
    return c.ingestion.upload(name, "application/pdf", data or sample_pdf(name)).document


def ingest_and_process(
    c: Container, name: str, data: bytes | None = None
) -> tuple[Document, WorkflowState]:
    doc = ingest(c, name, data)
    state = c.workflow.process(doc.document_id)
    return c.documents.get(doc.document_id), state


class FakeTextract:
    """Stand-in for the boto3 Textract client (returns LINE blocks)."""

    def __init__(self, lines: list[str] | None = None, fail: bool = False) -> None:
        self.lines = lines or []
        self.fail = fail
        self.calls = 0

    def detect_document_text(self, Document: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        self.calls += 1
        assert Document["Bytes"].startswith(b"\x89PNG")
        if self.fail:
            raise RuntimeError("throttled")
        return {
            "Blocks": [{"BlockType": "LINE", "Text": t} for t in self.lines]
            + [{"BlockType": "WORD", "Text": "ignored"}]
        }
