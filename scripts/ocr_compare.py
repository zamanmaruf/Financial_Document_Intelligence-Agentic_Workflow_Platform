"""Compare OCR engines on the synthetic scans whose printed text is known.

    python scripts/ocr_compare.py --engines tesseract,bedrock_vision,azure_vision \
        [--files edge_scanned_invoice.pdf ...] [--output evals/results/ocr_compare.json]

For each scan it reports the character error rate against the text the generator printed, how
many printed numbers were read exactly (and which were invented), how many expected field values
survive in the OCR text, latency, tokens and estimated cost. Vision engines read their model and
credentials from the environment or .env like the app (BEDROCK_MODEL_ID, AZURE_OPENAI_*,
OCR_VISION_MODEL); the cross-check with Tesseract is turned off so each engine is measured alone.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.config import (  # noqa: E402
    EmbeddingProviderName,
    LLMProviderName,
    OCRProviderName,
    Settings,
)
from app.core.errors import ProviderError  # noqa: E402
from app.domain.models import ModelInvocation  # noqa: E402
from app.evaluation.ocr_metrics import (  # noqa: E402
    character_error_rate,
    field_scores,
    number_scores,
)
from app.ingestion.extractors import DocumentTextExtractor  # noqa: E402
from app.observability.cost import CostEstimator  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.observability.metrics import InMemoryMetrics  # noqa: E402
from app.prompts.registry import PromptRegistry  # noqa: E402
from app.providers.factory import build_vision_llm_provider  # noqa: E402
from app.providers.ocr.tesseract import TesseractOCRExtractor  # noqa: E402
from app.providers.ocr.vision_llm import VisionLLMOCRExtractor  # noqa: E402
from app.services.model_gateway import ModelGateway  # noqa: E402

DEFAULT_FILES = [
    "edge_scanned_invoice.pdf",
    "edge_scanned_bank_statement.pdf",
    "edge_scanned_fund_summary.pdf",
]
ENGINES = ("tesseract", "bedrock_vision", "azure_vision")


class _Ledger:
    def __init__(self) -> None:
        self.calls: list[ModelInvocation] = []

    def save(self, inv: ModelInvocation) -> None:
        self.calls.append(inv)


def build_engine(name: str) -> tuple[DocumentTextExtractor, _Ledger | None, str]:
    if name == "tesseract":
        engine = TesseractOCRExtractor()
        if not engine.is_available():
            raise SystemExit("tesseract binary not installed")
        return engine, None, "tesseract"
    settings = Settings(
        ocr_provider=OCRProviderName(name),
        llm_provider=LLMProviderName.MOCK,
        embedding_provider=EmbeddingProviderName.HASHING,
        demo_mode=False,
        ocr_vision_cross_check=False,
    )
    ledger = _Ledger()
    provider = build_vision_llm_provider(settings)
    gateway = ModelGateway(
        provider=provider,
        prompts=PromptRegistry.load(settings.prompts_dir),
        invocations=ledger,
        metrics=InMemoryMetrics(),
        cost=CostEstimator.load(settings.config_dir),
        temperature=0.0,
        max_tokens=settings.ocr_vision_max_tokens,
        timeout_s=settings.llm_timeout_s,
        json_repair_attempts=settings.llm_json_repair_attempts,
    )
    extractor = VisionLLMOCRExtractor(gateway, settings.ocr_vision_max_edge_px)
    return extractor, ledger, f"{provider.provider_name}:{provider.model_name}"


def reference_texts() -> dict[str, tuple[str, dict[str, Any]]]:
    generator = importlib.import_module("generate_sample_data")
    return {
        doc.file: ("\n".join("\n".join(page) for page in doc.pages), doc.expected_fields)
        for doc in generator.DOCS
    }


def run_engine(name: str, files: list[str]) -> dict[str, Any]:
    engine, ledger, model = build_engine(name)
    references = reference_texts()
    documents: list[dict[str, Any]] = []
    for file in files:
        reference, expected_fields = references[file]
        data = (ROOT / "sample_data" / "pdfs" / file).read_bytes()
        calls_before = len(ledger.calls) if ledger else 0
        started = time.perf_counter()
        try:
            text = engine.extract(data).full_text
            error = None
        except ProviderError as exc:
            text, error = "", f"{exc.error_type}: {exc.message}"
        elapsed_ms = (time.perf_counter() - started) * 1000
        calls = ledger.calls[calls_before:] if ledger else []
        costs = [c.estimated_cost_usd for c in calls]
        documents.append(
            {
                "file": file,
                "error": error,
                "cer": round(character_error_rate(reference, text), 4),
                **number_scores(reference, text),
                **field_scores(expected_fields, text),
                "latency_ms": round(elapsed_ms, 1),
                "model_calls": len(calls),
                "input_tokens": sum(c.input_tokens for c in calls),
                "output_tokens": sum(c.output_tokens for c in calls),
                "cost_usd": None if None in costs else round(sum(c or 0.0 for c in costs), 6),
                "text": text,
            }
        )
    return {"engine": name, "model": model, "documents": documents, "summary": summarise(documents)}


def summarise(documents: list[dict[str, Any]]) -> dict[str, Any]:
    numbers_total = sum(d["numbers_total"] for d in documents)
    fields_total = sum(d["fields_total"] for d in documents)
    costs = [d["cost_usd"] for d in documents]
    return {
        "documents": len(documents),
        "errors": sum(1 for d in documents if d["error"]),
        "mean_cer": round(sum(d["cer"] for d in documents) / max(1, len(documents)), 4),
        "number_recall": round(
            sum(d["numbers_read_exactly"] for d in documents) / max(1, numbers_total), 4
        ),
        "spurious_numbers": sum(len(d["spurious_numbers"]) for d in documents),
        "field_recall": round(sum(d["fields_found"] for d in documents) / max(1, fields_total), 4),
        "mean_latency_ms": round(sum(d["latency_ms"] for d in documents) / max(1, len(documents))),
        "total_cost_usd": None if None in costs else round(sum(c or 0.0 for c in costs), 6),
    }


def print_table(results: list[dict[str, Any]]) -> None:
    print("\n| Engine | Model | Mean CER | Numbers read exactly | Invented numbers "
          "| Field values found | Mean latency / doc | Cost |")  # fmt: skip
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        s = r["summary"]
        cost = "n/a (unpriced)" if s["total_cost_usd"] is None else f"${s['total_cost_usd']:.4f}"
        print(
            f"| {r['engine']} | {r['model']} | {s['mean_cer']:.3f} | {s['number_recall']:.0%} "
            f"| {s['spurious_numbers']} | {s['field_recall']:.0%} "
            f"| {s['mean_latency_ms'] / 1000:.1f} s | {cost} |"
        )
    for r in results:
        for d in r["documents"]:
            if d["error"] or d["missed_numbers"] or d["spurious_numbers"] or d["fields_missing"]:
                print(
                    f"  {r['engine']} {d['file']}: error={d['error']} "
                    f"missed={d['missed_numbers']} invented={d['spurious_numbers']} "
                    f"fields_missing={d['fields_missing']}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", default="tesseract", help=f"comma-separated: {ENGINES}")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "ocr_compare.json")
    args = parser.parse_args()
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in engines if e not in ENGINES]
    if unknown:
        parser.error(f"unknown engines {unknown}; choose from {ENGINES}")

    configure_logging("WARNING", json_logs=False)
    logging.getLogger("app").setLevel(logging.ERROR)
    results = [run_engine(engine, args.files) for engine in engines]
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": args.files,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print_table(results)
    print(f"\nreport written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
