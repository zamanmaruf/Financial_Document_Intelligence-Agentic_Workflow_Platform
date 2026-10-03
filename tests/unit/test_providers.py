"""Provider adapters, mock provider, embeddings, vector store, storage and chunking."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import SecretStr

from app.core.config import LLMProviderName, Settings
from app.core.errors import InvalidDocumentError, ProviderConfigurationError, ProviderError
from app.core.registry import DocumentTypeRegistry
from app.domain.enums import DocumentType, TextExtractionMethod
from app.domain.models import Chunk, ExtractedText, PageText
from app.providers.embeddings.hashing import HashingEmbeddingProvider
from app.providers.factory import build_llm_provider
from app.providers.llm.base import LLMRequest
from app.providers.llm.langchain_chat import (
    AzureOpenAIProvider,
    BedrockClaudeProvider,
    build_azure_chat_model,
)
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.mock_handlers import default_handlers
from app.providers.storage.local import LocalDocumentStore
from app.providers.vectorstore.memory import InMemoryVectorStore, cosine
from app.retrieval.chunking import Chunker
from tests.support import ROOT


def request(prompt_name: str = "rag.grounded_answer", **variables: Any) -> LLMRequest:
    return LLMRequest(
        system="s", user="u", prompt_name=prompt_name, prompt_version="1.0.0", variables=variables
    )


class _ExplodingChatModel(GenericFakeChatModel):
    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("network down")


class TestLangChainAdapters:
    def test_bedrock_adapter_maps_response_and_usage(self) -> None:
        msg = AIMessage(
            content=[{"type": "text", "text": '{"answer": "ok"}'}],
            usage_metadata={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128},
            response_metadata={"stopReason": "end_turn"},
        )
        provider = BedrockClaudeProvider(
            model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
            region="us-east-1",
            temperature=0,
            max_tokens=256,
            timeout_s=10,
            chat_model=GenericFakeChatModel(messages=iter([msg])),
        )
        resp = provider.generate(request())
        assert resp.text == '{"answer": "ok"}'
        assert (resp.input_tokens, resp.output_tokens) == (120, 8)
        assert not resp.tokens_estimated
        assert resp.stop_reason == "end_turn"
        assert resp.provider == "bedrock"
        assert not provider.is_mock

    def test_azure_adapter_estimates_tokens_when_usage_missing(self) -> None:
        provider = AzureOpenAIProvider(
            endpoint=None,
            api_key=None,
            api_version="2024-06-01",
            deployment="gpt-4o",
            temperature=0,
            max_tokens=256,
            timeout_s=10,
            chat_model=GenericFakeChatModel(messages=iter([AIMessage(content="hello")])),
        )
        resp = provider.generate(request())
        assert resp.text == "hello"
        assert resp.tokens_estimated
        assert resp.provider == "azure_openai"
        assert resp.model_name == "gpt-4o"

    def test_vendor_exceptions_become_provider_errors(self) -> None:
        provider = BedrockClaudeProvider(
            model_id="m",
            region="us-east-1",
            temperature=0,
            max_tokens=10,
            timeout_s=1,
            chat_model=_ExplodingChatModel(messages=iter([])),
        )
        with pytest.raises(ProviderError, match="ConnectionError"):
            provider.generate(request())

    def test_azure_requires_configuration(self) -> None:
        with pytest.raises(ProviderConfigurationError):
            AzureOpenAIProvider(
                endpoint=None,
                api_key=None,
                api_version="v",
                deployment=None,
                temperature=0,
                max_tokens=10,
                timeout_s=1,
            )

    def test_real_sdk_clients_construct_without_network(self) -> None:
        """Constructing the real clients must not call the network (credentials resolve lazily)."""
        bedrock = BedrockClaudeProvider(
            model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
            region="us-east-1",
            temperature=0,
            max_tokens=64,
            timeout_s=5,
        )
        azure = AzureOpenAIProvider(
            endpoint="https://example.openai.azure.com",
            api_key="not-a-real-key",
            api_version="2024-06-01",
            deployment="gpt-4o",
            temperature=0,
            max_tokens=64,
            timeout_s=5,
        )
        assert bedrock.model_name.startswith("anthropic.")
        assert azure.provider_name == "azure_openai"


def _azure_payload(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "endpoint": "https://example.openai.azure.com",
        "api_key": "not-a-real-key",
        "api_version": "2025-04-01-preview",
        "deployment": "any-deployment-name",
        "temperature": 0.0,
        "max_tokens": 1024,
        "timeout_s": 5,
        "reasoning_effort": None,
    }
    kwargs.update(overrides)
    model = build_azure_chat_model(**kwargs)
    payload: dict[str, Any] = model._get_request_payload([HumanMessage("hi")])  # type: ignore[attr-defined]
    payload.pop("messages")
    return payload


class TestAzureRequestPayload:
    """Inspects the request body the real SDK client would send (no network)."""

    def test_standard_model_is_deterministic(self) -> None:
        payload = _azure_payload()
        assert payload["temperature"] == 0.0
        assert payload["seed"] == 0
        assert payload["max_completion_tokens"] == 1024
        assert "reasoning_effort" not in payload

    def test_reasoning_model_omits_sampling_params(self) -> None:
        payload = _azure_payload(reasoning_effort="low", max_tokens=8192)
        assert "temperature" not in payload
        assert "seed" not in payload
        assert payload["reasoning_effort"] == "low"
        assert payload["max_completion_tokens"] == 8192

    def test_settings_select_reasoning_budget_and_effort(self) -> None:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            llm_provider=LLMProviderName.AZURE_OPENAI,
            azure_openai_endpoint="https://example.openai.azure.com",
            azure_openai_api_key=SecretStr("not-a-real-key"),
            azure_openai_api_version="2025-04-01-preview",
            azure_openai_chat_deployment="gpt5-deploy",
            azure_openai_reasoning_model=True,
            azure_openai_reasoning_effort="minimal",
        )
        provider = build_llm_provider(settings, DocumentTypeRegistry.load(ROOT / "config"))
        assert isinstance(provider, AzureOpenAIProvider)
        chat: Any = provider._chat_model
        assert chat.reasoning_effort == "minimal"
        assert chat.max_tokens == settings.azure_openai_reasoning_max_tokens
        assert chat.temperature is None

    def test_reasoning_rejects_old_api_version(self) -> None:
        with pytest.raises(ValueError, match="2024-12-01-preview"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                azure_openai_reasoning_model=True,
                azure_openai_api_version="2024-10-21",
            )


class TestMockProvider:
    @pytest.fixture
    def handlers(self) -> Any:
        return default_handlers(DocumentTypeRegistry.load(ROOT / "config"))

    def test_deterministic(self, handlers: Any) -> None:
        req = request(
            "classification.document_type",
            document_text="INVOICE\nInvoice Number: 1\nBill To: X\nAmount Due: 5",
            supported_types="invoice, balance_sheet",
        )
        a = MockLLMProvider(handlers).generate(req)
        b = MockLLMProvider(handlers).generate(req)
        assert a.text == b.text
        assert json.loads(a.text)["document_type"] == "invoice"
        assert a.is_mock and a.tokens_estimated

    def test_fault_injection(self, handlers: Any) -> None:
        provider = MockLLMProvider(handlers, fail_first_n=1, malformed_first_n=1)
        req = request(
            "classification.document_type", document_text="invoice", supported_types="invoice"
        )
        with pytest.raises(ProviderError):
            provider.generate(req)
        assert "{" not in provider.generate(req).text  # malformed
        assert json.loads(provider.generate(req).text)  # recovered

    def test_unknown_prompt(self, handlers: Any) -> None:
        with pytest.raises(ProviderConfigurationError):
            MockLLMProvider(handlers).generate(request("nope"))


class TestEmbeddingsAndVectorStore:
    def test_hashing_embeddings_normalized_and_deterministic(self) -> None:
        emb = HashingEmbeddingProvider(dimension=64)
        v1 = emb.embed_query("closing balance")
        assert v1 == emb.embed_query("closing balance")
        assert sum(x * x for x in v1) == pytest.approx(1.0)
        assert len(v1) == 64

    def test_lexical_similarity_ordering(self) -> None:
        emb = HashingEmbeddingProvider()
        q = emb.embed_query("closing balance")
        related = emb.embed_query("Closing Balance: 277,539.57")
        unrelated = emb.embed_query("Management fee 0.75%")
        assert cosine(q, related) > cosine(q, unrelated)

    def test_memory_store_filters_and_delete(self) -> None:
        emb = HashingEmbeddingProvider()
        store = InMemoryVectorStore()
        chunks = [
            Chunk(
                chunk_id=f"c{i}",
                document_id=f"d{i % 2}",
                text=t,
                page_number=1,
                chunk_index=i,
                start_char=0,
                end_char=len(t),
                metadata={"document_id": f"d{i % 2}", "document_type": "invoice"},
            )
            for i, t in enumerate(["amount due 100", "closing balance 5"])
        ]
        store.upsert(chunks, emb.embed_documents([c.text for c in chunks]))
        hits = store.query(emb.embed_query("amount due"), 5, {"document_id": "d0"})
        assert [chunk.chunk_id for chunk, _score in hits] == ["c0"]
        store.delete_document("d0")
        assert store.count() == 1


class TestLocalDocumentStore:
    def test_atomic_save_permissions_and_roundtrip(self, tmp_path: Path) -> None:
        store = LocalDocumentStore(tmp_path / "docs")
        doc_id = "doc_" + "a" * 32
        path = Path(store.save(doc_id, b"%PDF-1.4 data"))
        assert store.load(doc_id) == b"%PDF-1.4 data"
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert not list((tmp_path / "docs").glob(".upload-*"))

    @pytest.mark.parametrize("bad_id", ["../etc/passwd", "doc_../../x", "doc_ABC", "x" * 10, ""])
    def test_rejects_path_traversal(self, tmp_path: Path, bad_id: str) -> None:
        store = LocalDocumentStore(tmp_path / "docs")
        with pytest.raises(InvalidDocumentError):
            store.save(bad_id, b"x")


class TestChunker:
    TEXT = ExtractedText(
        pages=[
            PageText(page_number=1, text="Account Number: 1234567890\n" + "Line of text. " * 80),
            PageText(page_number=2, text="Closing Balance: 277,539.57"),
        ],
        method=TextExtractionMethod.NATIVE_PDF,
    )

    def test_chunks_are_per_page_masked_and_deterministic(self) -> None:
        chunker = Chunker(chunk_size=300, chunk_overlap=40)
        a = chunker.chunk("doc_1", self.TEXT, DocumentType.BANK_STATEMENT)
        b = chunker.chunk("doc_1", self.TEXT, DocumentType.BANK_STATEMENT)
        assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
        assert {c.page_number for c in a} == {1, 2}
        assert all("1234567890" not in c.text for c in a)
        assert any("****7890" in c.text for c in a)
        assert all(len(c.text) <= 300 for c in a)
        assert a[0].metadata["document_type"] == "bank_statement"


class TestPdfInspection:
    def test_active_content_markers_are_flagged(self) -> None:
        from app.ingestion.pdf import inspect_pdf
        from tests.support import make_pdf

        clean = make_pdf(["Invoice Number: 1"])
        assert not inspect_pdf(clean).has_active_content
        import io

        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(clean)))
        writer.add_js("app.alert('x');")
        writer.add_attachment("payload.txt", b"hidden")
        buf = io.BytesIO()
        writer.write(buf)
        assert inspect_pdf(buf.getvalue()).has_active_content

    def test_page_count_and_text_layer(self) -> None:
        from app.ingestion.pdf import inspect_pdf
        from tests.support import make_pdf

        info = inspect_pdf(make_pdf(["page one", "page two"]))
        assert info.page_count == 2 and info.has_text_layer
