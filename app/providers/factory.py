"""Configuration-driven provider selection. The only place provider classes are chosen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import (
    EmbeddingProviderName,
    LLMProviderName,
    MetricsBackendName,
    OCRProviderName,
    Settings,
    VectorStoreName,
)
from app.core.errors import ProviderConfigurationError
from app.core.registry import DocumentTypeRegistry
from app.ingestion.extractors import DocumentTextExtractor
from app.observability.metrics import InMemoryMetrics, OpenTelemetryMetrics
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.hashing import HashingEmbeddingProvider
from app.providers.embeddings.langchain_embeddings import (
    azure_openai_embeddings,
    bedrock_embeddings,
)
from app.providers.llm.base import LLMProvider
from app.providers.llm.langchain_chat import AzureOpenAIProvider, BedrockClaudeProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.mock_handlers import default_handlers
from app.providers.ocr.tesseract import TesseractOCRExtractor
from app.providers.ocr.textract import TextractOCRExtractor
from app.providers.ocr.vision_llm import VisionLLMOCRExtractor
from app.providers.vectorstore.base import VectorStore
from app.providers.vectorstore.chroma import ChromaVectorStore
from app.providers.vectorstore.memory import InMemoryVectorStore

if TYPE_CHECKING:
    from app.services.model_gateway import ModelGateway


def build_llm_provider(settings: Settings, registry: DocumentTypeRegistry) -> LLMProvider:
    match settings.llm_provider:
        case LLMProviderName.MOCK:
            return MockLLMProvider(default_handlers(registry))
        case LLMProviderName.BEDROCK:
            return BedrockClaudeProvider(
                model_id=settings.bedrock_model_id,
                region=settings.aws_region,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                timeout_s=settings.llm_timeout_s,
            )
        case LLMProviderName.AZURE_OPENAI:
            key = settings.azure_openai_api_key
            reasoning = settings.azure_openai_reasoning_model
            return AzureOpenAIProvider(
                endpoint=settings.azure_openai_endpoint,
                api_key=key.get_secret_value() if key else None,
                api_version=settings.azure_openai_api_version,
                deployment=settings.azure_openai_chat_deployment,
                temperature=settings.llm_temperature,
                max_tokens=(
                    settings.azure_openai_reasoning_max_tokens
                    if reasoning
                    else settings.llm_max_tokens
                ),
                timeout_s=settings.llm_timeout_s,
                reasoning_effort=settings.azure_openai_reasoning_effort if reasoning else None,
            )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    match settings.embedding_provider:
        case EmbeddingProviderName.HASHING:
            return HashingEmbeddingProvider(settings.hashing_embedding_dim)
        case EmbeddingProviderName.BEDROCK:
            return bedrock_embeddings(
                settings.bedrock_embedding_model_id,
                settings.aws_region,
                timeout_s=settings.embedding_timeout_s,
            )
        case EmbeddingProviderName.AZURE_OPENAI:
            key = settings.azure_openai_api_key
            return azure_openai_embeddings(
                settings.azure_openai_endpoint,
                key.get_secret_value() if key else None,
                settings.azure_openai_api_version,
                settings.azure_openai_embedding_deployment,
                timeout_s=settings.embedding_timeout_s,
            )


def build_vector_store(settings: Settings, embedding_model: str) -> VectorStore:
    match settings.vector_store:
        case VectorStoreName.CHROMA:
            return ChromaVectorStore(settings.data_dir / "chroma", embedding_model)
        case VectorStoreName.MEMORY:
            return InMemoryVectorStore()


def build_vision_llm_provider(settings: Settings) -> LLMProvider:
    """The multimodal model behind vision OCR; always a real provider, never the mock."""
    model = settings.ocr_vision_model
    match settings.ocr_provider:
        case OCRProviderName.BEDROCK_VISION:
            return BedrockClaudeProvider(
                model_id=model or settings.bedrock_model_id,
                region=settings.aws_region,
                temperature=0.0,
                max_tokens=settings.ocr_vision_max_tokens,
                timeout_s=settings.llm_timeout_s,
            )
        case OCRProviderName.AZURE_VISION:
            key = settings.azure_openai_api_key
            reasoning = settings.azure_openai_reasoning_model and not model
            return AzureOpenAIProvider(
                endpoint=settings.azure_openai_endpoint,
                api_key=key.get_secret_value() if key else None,
                api_version=settings.azure_openai_api_version,
                deployment=model or settings.azure_openai_chat_deployment,
                temperature=0.0,
                max_tokens=settings.ocr_vision_max_tokens,
                timeout_s=settings.llm_timeout_s,
                reasoning_effort=settings.azure_openai_reasoning_effort if reasoning else None,
            )
        case _:
            raise ProviderConfigurationError(
                f"OCR provider {settings.ocr_provider.value} does not use a vision model"
            )


def build_ocr_extractor(
    settings: Settings, vision_gateway: ModelGateway | None = None
) -> DocumentTextExtractor | None:
    match settings.ocr_provider:
        case OCRProviderName.NONE:
            return None
        case OCRProviderName.TEXTRACT:
            return TextractOCRExtractor(region=settings.textract_region or settings.aws_region)
        case OCRProviderName.TESSERACT:
            return TesseractOCRExtractor()
        case OCRProviderName.AUTO:
            engine = TesseractOCRExtractor()
            return engine if engine.is_available() else None
        case OCRProviderName.BEDROCK_VISION | OCRProviderName.AZURE_VISION:
            if vision_gateway is None:
                raise ProviderConfigurationError("vision OCR needs a model gateway")
            tesseract = TesseractOCRExtractor()
            cross_check = (
                tesseract if settings.ocr_vision_cross_check and tesseract.is_available() else None
            )
            return VisionLLMOCRExtractor(
                vision_gateway, settings.ocr_vision_max_edge_px, cross_check=cross_check
            )


def build_metrics(settings: Settings) -> InMemoryMetrics:
    if settings.metrics_backend == MetricsBackendName.OTEL:
        return OpenTelemetryMetrics()
    return InMemoryMetrics()
