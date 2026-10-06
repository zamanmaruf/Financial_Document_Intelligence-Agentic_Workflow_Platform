"""Compare extraction models on the held-out fine-tuning test set and the original samples.

    python scripts/finetune/evaluate.py \\
        --target base-nano=azure-ft:gpt-4.1-nano \\
        --target fine-tuned-nano=azure-ft:gpt-4.1-nano-docintel-ft \\
        --target base-mini=azure:gpt-4.1-mini-1 \\
        --output evals/results/finetune_eval.json

Each target is LABEL=RESOURCE:DEPLOYMENT, where RESOURCE is "azure" (the main Azure OpenAI
resource), "azure-ft" (the fine-tuning resource) or "mock" (offline, no deployment). Every
target runs the production EntityExtractor with the prompt version the dataset was built with,
on the 80 held-out test documents (layouts and names never seen in training) and on the 25
labelled sample documents. Deployment names must be priced in config/pricing.yaml (aliases)
for cost to be reported.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from azure_env import azure_credentials  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.core.config import LLMProviderName, Settings  # noqa: E402
from app.core.registry import DocumentTypeRegistry  # noqa: E402
from app.core.resilience import RetryPolicy  # noqa: E402
from app.extraction.service import PROMPT_NAME, EntityExtractor  # noqa: E402
from app.finetune.evaluation import (  # noqa: E402
    EvalDoc,
    InvocationList,
    RecordingProvider,
    evaluate_extraction,
    heldout_docs,
    sample_docs,
)
from app.observability.cost import CostEstimator  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.observability.metrics import InMemoryMetrics  # noqa: E402
from app.prompts.registry import PromptRegistry  # noqa: E402
from app.providers.factory import build_llm_provider  # noqa: E402
from app.services.model_gateway import ModelGateway  # noqa: E402

DATA = ROOT / "evals" / "finetune"
SUMMARY = [
    "field_accuracy",
    "normalized_match",
    "missing_field_rate",
    "hallucinated_field_rate",
    "json_first_reply_valid_rate",
    "json_repaired_documents",
    "call_failures",
    "latency_ms_p50",
    "latency_ms_p95",
    "cost_per_document_usd",
]


def _settings(resource: str, deployment: str) -> Settings:
    if resource == "mock":
        return Settings(llm_provider=LLMProviderName.MOCK)
    if resource not in ("azure", "azure-ft"):
        raise SystemExit(f"unknown resource {resource!r}: use azure, azure-ft or mock")
    endpoint, key, version = azure_credentials("finetune" if resource == "azure-ft" else "main")
    return Settings(
        llm_provider=LLMProviderName.AZURE_OPENAI,
        azure_openai_endpoint=endpoint,
        azure_openai_api_key=SecretStr(key),
        azure_openai_api_version=version,
        azure_openai_chat_deployment=deployment,
        azure_openai_reasoning_model=False,
        llm_temperature=0.0,
    )


def _run(
    label: str, spec: str, datasets: dict[str, list[EvalDoc]], prompt_version: str
) -> dict[str, Any]:
    resource, _, deployment = spec.partition(":")
    settings = _settings(resource, deployment)
    registry = PromptRegistry.load(ROOT / "prompts")
    provider = build_llm_provider(settings, DocumentTypeRegistry.load(ROOT / "config"))
    recorder = RecordingProvider(provider)
    invocations = InvocationList()
    gateway = ModelGateway(
        provider=recorder,
        prompts=PromptRegistry([registry.get(PROMPT_NAME, prompt_version)]),
        invocations=invocations,
        metrics=InMemoryMetrics(),
        cost=CostEstimator.load(ROOT / "config"),
        temperature=0.0,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
        retry_policy=RetryPolicy(
            max_retries=settings.llm_max_retries, backoff_s=settings.llm_retry_backoff_s
        ),
        json_repair_attempts=settings.llm_json_repair_attempts,
    )
    extractor = EntityExtractor(
        gateway, settings.extraction_min_confidence, settings.amount_tolerance_ratio
    )
    out: dict[str, Any] = {
        "resource": resource,
        "deployment": deployment or None,
        "model_name": provider.model_name,
        "datasets": {},
    }
    for name, docs in datasets.items():
        print(f"{label}: {name} ({len(docs)} documents)", flush=True)
        out["datasets"][name] = evaluate_extraction(docs, extractor, recorder, invocations)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--target", action="append", required=True, help="LABEL=RESOURCE:DEPLOYMENT"
    )
    parser.add_argument("--datasets", default="heldout,samples")
    parser.add_argument("--limit", type=int, default=None, help="first N documents per dataset")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    configure_logging("WARNING", json_logs=False)

    manifest = json.loads((DATA / "manifest.json").read_text())
    prompt_version = manifest["prompt"]["version"]
    available = {
        "heldout": lambda: heldout_docs(DATA),
        "samples": lambda: sample_docs(ROOT / "sample_data"),
    }
    datasets = {}
    for name in args.datasets.split(","):
        if name not in available:
            raise SystemExit(f"unknown dataset {name!r}")
        datasets[name] = available[name]()[: args.limit]

    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt": manifest["prompt"],
        "dataset_sha256": {n: f["sha256"] for n, f in manifest["files"].items()},
        "targets": {},
    }
    for target in args.target:
        label, _, spec = target.partition("=")
        report["targets"][label] = _run(label, spec, datasets, prompt_version)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for label, result in report["targets"].items():
        for name, m in result["datasets"].items():
            print(f"{label:18} {name:8} " + "  ".join(f"{k}={m[k]}" for k in SUMMARY))
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
