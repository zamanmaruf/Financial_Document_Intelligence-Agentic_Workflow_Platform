"""Export the landing page's hero image: a real sample invoice with its extracted fields boxed.

Runs the offline engine on ``invoice_01_acme.pdf``, locates each field's evidence on the page and
writes a PNG plus the boxes as JSON into ``web/src/assets/hero/`` (bundled and fingerprinted by
Vite), so the landing page shows real output without calling the API.

Usage: python scripts/export_hero_assets.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.documents.pages import LocateQuery, PageService  # noqa: E402
from app.services.container import build_container  # noqa: E402

SAMPLE = ROOT / "sample_data" / "pdfs" / "invoice_01_acme.pdf"
OUT = ROOT / "web" / "src" / "assets" / "hero"
FIELDS = ("invoice_number", "invoice_date", "vendor", "customer", "subtotal", "tax", "amount_due")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None,
            data_dir=Path(tmp),
            site_dir=Path(tmp) / "no-site",
            llm_provider="mock",
            vector_store="memory",
            log_level="WARNING",
        )
        container = build_container(settings)
        try:
            outcome = container.ingestion.upload(
                SAMPLE.name, "application/pdf", SAMPLE.read_bytes(), "system", "default"
            )
            doc_id = outcome.document.document_id
            container.workflow.process(doc_id, "system")
            entities = container.extractions.list_for_document(doc_id)[0].entities
            picked = [e for e in entities if e.name in FIELDS and e.evidence and e.evidence.snippet]
            pages = PageService(container.store)
            queries = [
                LocateQuery(e.evidence.snippet, e.evidence.page_number)
                for e in picked
                if e.evidence
            ]
            located = pages.locate(doc_id, queries).outcomes
            image = pages.render(doc_id, 1)
        finally:
            container.close()

    boxes = []
    for entity, found in zip(picked, located, strict=True):
        page_one = [m for m in found.matches if m.page_number == 1]
        if not page_one:
            continue
        boxes.append(
            {
                "name": entity.name,
                "value": entity.value,
                "snippet": entity.evidence.snippet if entity.evidence else None,
                "rects": [
                    {"x": r.x, "y": r.y, "width": r.width, "height": r.height}
                    for r in page_one[0].rects
                ],
            }
        )
    (OUT / "invoice.png").write_bytes(image.png)
    meta = {
        "source": SAMPLE.name,
        "width": image.width,
        "height": image.height,
        "fields": boxes,
    }
    (OUT / "invoice.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}/invoice.png and invoice.json ({len(boxes)} boxes)")


if __name__ == "__main__":
    main()
