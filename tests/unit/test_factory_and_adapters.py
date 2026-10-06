from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from app.core.config import (
    EmbeddingProviderName,
    LLMProviderName,
    MetricsBackendName,
    OCRProviderName,
    VectorStoreName,
)
from app.core.errors import ProviderConfigurationError, ProviderError
from app.core.registry import DocumentTypeRegistry
from app.observability.metrics import OpenTelemetryMetrics
from app.providers import factory
from app.providers.embeddings.langchain_embeddings import (
    LangChainEmbeddingProvider,
    azure_openai_embeddings,
    bedrock_embeddings,
)
from app.providers.ocr.textract import TextractOCRExtractor
from app.providers.vectorstore.chroma import ChromaVectorStore
from tests.support import ROOT, FakeTextract, make_settings, sample_pdf


class _BrokenEmbeddings(DeterministicFakeEmbedding):
    def embed_query(self, text: str) -> list[float]:
        raise ConnectionError("down")


class TestEmbeddingAdapters:
    def test_langchain_embedding_adapter(self) -> None:
        provider = LangChainEmbeddingProvider(DeterministicFakeEmbedding(size=8), "bedrock", "m")
        assert len(provider.embed_query("x")) == 8
        assert len(provider.embed_documents(["a", "b"])) == 2
        assert not provider.is_mock

    def test_errors_are_wrapped(self) -> None:
        provider = LangChainEmbeddingProvider(_BrokenEmbeddings(size=8), "bedrock", "m")
        with pytest.raises(ProviderError, match="ConnectionError"):
            provider.embed_query("x")

    def test_real_clients_construct_offline(self) -> None:
        assert bedrock_embeddings("amazon.titan-embed-text-v2:0", "us-east-1").model_name
        azure = azure_openai_embeddings("https://x.openai.azure.com", "k", "2024-06-01", "emb")
        assert azure.provider_name == "azure_openai"
        with pytest.raises(ProviderConfigurationError):
            azure_openai_embeddings(None, None, "v", None)

    def test_cloud_embedding_clients_are_bounded(self) -> None:
        # Embedding calls bypass the gateway's retry loop, so the clients carry their own limits.
        bedrock = bedrock_embeddings("amazon.titan-embed-text-v2:0", "us-east-1", timeout_s=12.0)
        config = bedrock._embeddings.config  # type: ignore[attr-defined]
        assert config.read_timeout == 12.0
        assert config.connect_timeout == 10.0
        assert config.retries == {"total_max_attempts": 3, "mode": "standard"}
        azure = azure_openai_embeddings(
            "https://x.openai.azure.com", "k", "2024-06-01", "emb", timeout_s=7.0
        )
        assert azure._embeddings.request_timeout == 7.0  # type: ignore[attr-defined]
        assert azure._embeddings.max_retries == 2  # type: ignore[attr-defined]


class TestFactory:
    def test_mock_defaults(self, tmp_path: Path) -> None:
        s = make_settings(tmp_path)
        registry = DocumentTypeRegistry.load(ROOT / "config")
        assert factory.build_llm_provider(s, registry).is_mock
        assert factory.build_embedding_provider(s).is_mock

    def test_cloud_selection(self, tmp_path: Path) -> None:
        registry = DocumentTypeRegistry.load(ROOT / "config")
        bedrock = make_settings(
            tmp_path,
            llm_provider=LLMProviderName.BEDROCK,
            embedding_provider=EmbeddingProviderName.BEDROCK,
        )
        assert factory.build_llm_provider(bedrock, registry).provider_name == "bedrock"
        assert factory.build_embedding_provider(bedrock).provider_name == "bedrock"
        azure = make_settings(tmp_path, llm_provider=LLMProviderName.AZURE_OPENAI)
        with pytest.raises(ProviderConfigurationError):
            factory.build_llm_provider(azure, registry)

    def test_vector_store_ocr_and_metrics_selection(self, tmp_path: Path) -> None:
        chroma = make_settings(tmp_path, vector_store=VectorStoreName.CHROMA)
        assert isinstance(
            factory.build_vector_store(chroma, "hashing-lexical-512"), ChromaVectorStore
        )
        assert (
            factory.build_ocr_extractor(make_settings(tmp_path, ocr_provider=OCRProviderName.NONE))
            is None
        )
        assert isinstance(
            factory.build_ocr_extractor(
                make_settings(tmp_path, ocr_provider=OCRProviderName.TEXTRACT)
            ),
            TextractOCRExtractor,
        )
        otel = make_settings(tmp_path, metrics_backend=MetricsBackendName.OTEL)
        metrics = factory.build_metrics(otel)
        assert isinstance(metrics, OpenTelemetryMetrics)
        metrics.increment("x_total")
        metrics.observe("y_ms", 1.0)
        assert metrics.snapshot()["counters"]["x_total"][0]["value"] == 1.0


class TestTextract:
    def test_lines_are_collected_per_page(self) -> None:
        client = FakeTextract(["INVOICE", "Amount Due: 1,250.00"])
        text = TextractOCRExtractor("us-east-1", client=client, dpi=50).extract(
            sample_pdf("edge_scanned_invoice.pdf")
        )
        assert client.calls == len(text.pages) >= 1
        assert text.pages[0].text == "INVOICE\nAmount Due: 1,250.00"
        assert text.method.value == "ocr_textract"

    def test_failures_become_provider_errors(self) -> None:
        extractor = TextractOCRExtractor("us-east-1", client=FakeTextract(fail=True), dpi=50)
        with pytest.raises(ProviderError, match="Textract"):
            extractor.extract(sample_pdf("edge_scanned_invoice.pdf"))
