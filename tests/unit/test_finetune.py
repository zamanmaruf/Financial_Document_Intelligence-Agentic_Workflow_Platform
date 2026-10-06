from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.core.text import normalize_ws
from app.domain.enums import DocumentType
from app.extraction.service import EntityExtractor
from app.finetune.corpus import DEFAULT_SEED, SPLITS, generate_corpus, stem_of
from app.finetune.estimate import (
    check_budget,
    estimate_training,
    record_tokens,
    training_prices,
)
from app.finetune.evaluation import (
    InvocationList,
    RecordingProvider,
    evaluate_extraction,
    heldout_docs,
)
from app.finetune.records import check_target, extracted_text, prompt_messages, target_output
from app.observability.cost import CostEstimator
from app.observability.metrics import InMemoryMetrics
from app.prompts.registry import PromptRegistry
from app.providers.llm.base import LLMRequest, LLMResponse
from app.services.model_gateway import ModelGateway

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evals" / "finetune"


@pytest.fixture(scope="module")
def corpus() -> list[Any]:
    return generate_corpus()


@pytest.fixture(scope="module")
def registry() -> PromptRegistry:
    return PromptRegistry.load(ROOT / "prompts")


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads((DATA / "manifest.json").read_text())


def _rows(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATA / name).read_text().splitlines()]


# ------------------------------------------------------------------------------------ corpus


def test_corpus_is_deterministic_for_a_seed(corpus: list[Any]) -> None:
    again = generate_corpus(DEFAULT_SEED)
    assert [(d.doc_id, d.pages, d.fields) for d in again] == [
        (d.doc_id, d.pages, d.fields) for d in corpus
    ]
    other = generate_corpus(DEFAULT_SEED + 1)
    assert [d.pages for d in other] != [d.pages for d in corpus]


def test_split_sizes_are_balanced_across_types(corpus: list[Any]) -> None:
    assert Counter(d.split for d in corpus) == {"train": 200, "validation": 40, "test": 80}
    per_type = Counter((d.document_type, d.split) for d in corpus)
    for document_type in {d.document_type for d in corpus}:
        assert per_type[(document_type, "train")] == 40
        assert per_type[(document_type, "validation")] == 8
        assert per_type[(document_type, "test")] == 16


def test_no_layout_family_or_name_crosses_splits(corpus: list[Any]) -> None:
    families = {s: {d.family for d in corpus if d.split == s} for s in SPLITS}
    stems = {
        s: {stem_of(n).casefold() for d in corpus if d.split == s for n in d.names} for s in SPLITS
    }
    for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]:
        assert not families[a] & families[b]
        assert not stems[a] & stems[b], stems[a] & stems[b]


def test_names_do_not_reuse_sample_data_companies(corpus: list[Any]) -> None:
    truth = json.loads((ROOT / "sample_data" / "ground_truth.json").read_text())
    sample_stems = {
        stem_of(v).casefold()
        for doc in truth["documents"]
        for k, v in doc["expected_fields"].items()
        if k in {"company_name", "vendor", "customer", "bank_name", "fund_name"} and v
    }
    generated = {stem_of(n).casefold() for d in corpus for n in d.names}
    assert not generated & sample_stems


def test_every_expected_value_sits_on_its_recorded_line(corpus: list[Any]) -> None:
    for doc in corpus:
        for name, truth in doc.fields.items():
            if truth.value is None:
                continue
            page = doc.pages[truth.page - 1]
            assert truth.line in [ln.strip() for ln in page], (doc.doc_id, name)
            assert truth.raw_text in truth.line


# ---------------------------------------------------------------------------- committed files


def test_committed_files_match_the_manifest(manifest: dict[str, Any]) -> None:
    for name, meta in manifest["files"].items():
        data = (DATA / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], f"{name}: rebuild the dataset"


def test_committed_documents_match_a_fresh_render(corpus: list[Any]) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from generate_sample_data import render_text_pdf

    from app.ingestion.pdf import PypdfTextExtractor

    reader = PypdfTextExtractor()
    rows = _rows("documents.jsonl")
    assert [r["doc_id"] for r in rows] == [d.doc_id for d in corpus]
    for row, doc in zip(rows, corpus, strict=True):
        text = reader.extract(render_text_pdf(doc.pages))
        assert row["pages"] == [p.text for p in text.pages], doc.doc_id
        assert row["expected"] == doc.expected()


def test_every_training_record_uses_the_production_prompt_and_is_accepted(
    registry: PromptRegistry, manifest: dict[str, Any]
) -> None:
    version = manifest["prompt"]["version"]
    assert registry.get("extraction.financial_entities", version).hash == manifest["prompt"]["hash"]
    docs = _rows("documents.jsonl")
    for split, name in [("train", "train.jsonl"), ("validation", "validation.jsonl")]:
        split_docs = [d for d in docs if d["split"] == split]
        records = _rows(name)
        assert len(records) == len(split_docs)
        for doc, record in zip(split_docs, records, strict=True):
            roles = [m["role"] for m in record["messages"]]
            assert roles == ["system", "user", "assistant"]
            document_type = DocumentType(doc["document_type"])
            text = extracted_text(doc["pages"])
            system, user = prompt_messages(registry, version, document_type, text)
            assert record["messages"][0]["content"] == system
            assert record["messages"][1]["content"] == user
            answer = record["messages"][2]["content"]
            problems = check_target(registry, version, document_type, text, answer, doc["expected"])
            assert not problems, (doc["doc_id"], problems)


def test_test_documents_never_appear_in_training_records() -> None:
    docs = _rows("documents.jsonl")
    users = [
        normalize_ws(r["messages"][1]["content"])
        for name in ("train.jsonl", "validation.jsonl")
        for r in _rows(name)
    ]
    first_pages = {d["doc_id"]: normalize_ws(d["pages"][0]) for d in docs}
    for d in docs:
        found = any(first_pages[d["doc_id"]] in u for u in users)
        assert found == (d["split"] != "test"), d["doc_id"]


def test_check_target_rejects_wrong_values_and_invented_evidence(
    registry: PromptRegistry, manifest: dict[str, Any]
) -> None:
    version = manifest["prompt"]["version"]
    doc = next(d for d in _rows("documents.jsonl") if d["document_type"] == "invoice")
    record = next(r for r in _rows("train.jsonl") if doc["pages"][0] in r["messages"][1]["content"])
    answer = json.loads(record["messages"][2]["content"])
    answer["fields"]["amount_due"]["value"] = 1.0
    answer["fields"]["vendor"]["evidence_snippet"] = "a line that is not in the document"
    problems = check_target(
        registry,
        version,
        DocumentType.INVOICE,
        extracted_text(doc["pages"]),
        json.dumps(answer),
        doc["expected"],
    )
    assert any(p.startswith("amount_due: expected") for p in problems)
    assert "vendor: evidence not verified" in problems


# ---------------------------------------------------------------------------------- estimate


class _CharEncoding:
    """One token per character: makes the arithmetic easy to check."""

    def encode(self, text: str) -> list[int]:
        return [ord(c) for c in text]


def test_record_tokens_counts_content_roles_and_overhead() -> None:
    record = {
        "messages": [{"role": "user", "content": "abcd"}, {"role": "assistant", "content": "xy"}]
    }
    # reply primer 3 + per message (3 + role + content)
    assert record_tokens(record, _CharEncoding()) == 3 + (3 + 4 + 4) + (3 + 9 + 2)


def test_estimate_multiplies_tokens_by_epochs_and_price() -> None:
    record = {"messages": [{"role": "user", "content": "a" * 991}]}  # 3 + 3 + 4 + 991 = 1001
    est = estimate_training(
        [record, record], "m", epochs=3, price_per_1m_tokens=2.0, encoding=_CharEncoding()
    )
    assert est.tokens_per_epoch == 2002
    assert est.max_example_tokens == 1001
    assert est.billed_tokens == 6006
    assert est.cost_usd == pytest.approx(6006 / 1_000_000 * 2.0, abs=1e-4)
    with pytest.raises(ValueError):
        estimate_training(
            [record], "m", epochs=0, price_per_1m_tokens=2.0, encoding=_CharEncoding()
        )


def test_budget_guard() -> None:
    check_budget(1.064, confirmed_usd=1.07, cap_usd=30)
    with pytest.raises(ValueError, match="rerun with --confirm-cost-usd"):
        check_budget(1.064, confirmed_usd=None, cap_usd=30)
    with pytest.raises(ValueError, match="below the estimated"):
        check_budget(1.064, confirmed_usd=1.06, cap_usd=30)
    with pytest.raises(ValueError, match=r"exceeds the \$30\.00 cap"):
        check_budget(31.0, confirmed_usd=40, cap_usd=30)
    with pytest.raises(ValueError, match=r"exceeds the \$30\.00 cap"):
        check_budget(1.0, confirmed_usd=45, cap_usd=30)


def test_training_prices_are_configured_for_both_candidate_models() -> None:
    prices = training_prices(ROOT / "config")
    assert set(prices) >= {"gpt-4.1-nano-2025-04-14", "gpt-4.1-mini-2025-04-14"}
    assert all(p > 0 for p in prices.values())


# -------------------------------------------------------------------------------- evaluation


class _Replies:
    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "azure_openai"

    @property
    def model_name(self) -> str:
        return "unpriced-deployment"

    @property
    def is_mock(self) -> bool:
        return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        text = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return LLMResponse(text=text, provider="azure_openai", model_name="unpriced-deployment")


def test_evaluation_counts_repairs_and_scores_fields(
    registry: PromptRegistry, manifest: dict[str, Any], corpus: list[Any]
) -> None:
    doc = heldout_docs(DATA)[0]
    synthetic = next(d for d in corpus if d.doc_id == doc.doc_id)
    correct = json.dumps(target_output(synthetic, doc.text))
    recorder = RecordingProvider(_Replies(["not json at all", correct]))
    invocations = InvocationList()
    gateway = ModelGateway(
        provider=recorder,
        prompts=PromptRegistry(
            [registry.get("extraction.financial_entities", manifest["prompt"]["version"])]
        ),
        invocations=invocations,
        metrics=InMemoryMetrics(),
        cost=CostEstimator({}),
        json_repair_attempts=1,
    )
    extractor = EntityExtractor(gateway, 0.6, 0.005)
    result = evaluate_extraction([doc], extractor, recorder, invocations)
    assert result["n_documents"] == 1
    assert result["json_first_reply_valid_rate"] == 0.0
    assert result["json_repaired_documents"] == 1
    assert result["field_accuracy"] == 1.0
    assert result["mismatches"] == []
    assert result["cost_per_document_usd"] is None  # unpriced deployment, not free
