"""Cloud embedding providers via LangChain adapters (Bedrock Titan, Azure OpenAI)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from app.core.errors import ProviderConfigurationError, ProviderError

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings


class LangChainEmbeddingProvider:
    def __init__(self, embeddings: Embeddings, provider_name: str, model_name: str) -> None:
        self._embeddings = embeddings
        self._provider_name = provider_name
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_mock(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            return [list(map(float, v)) for v in self._embeddings.embed_documents(texts)]
        except Exception as exc:
            raise ProviderError(
                f"{self._provider_name} embedding failed: {type(exc).__name__}"
            ) from exc

    def embed_query(self, text: str) -> list[float]:
        try:
            return list(map(float, self._embeddings.embed_query(text)))
        except Exception as exc:
            raise ProviderError(
                f"{self._provider_name} embedding failed: {type(exc).__name__}"
            ) from exc


def bedrock_embeddings(model_id: str, region: str) -> LangChainEmbeddingProvider:
    from langchain_aws import BedrockEmbeddings

    return LangChainEmbeddingProvider(
        BedrockEmbeddings(model_id=model_id, region_name=region),
        provider_name="bedrock",
        model_name=model_id,
    )


def azure_openai_embeddings(
    endpoint: str | None, api_key: str | None, api_version: str, deployment: str | None
) -> LangChainEmbeddingProvider:
    if not endpoint or not api_key or not deployment:
        raise ProviderConfigurationError(
            "Azure OpenAI embeddings require endpoint, api key and "
            "DOCINTEL_AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        )
    from langchain_openai import AzureOpenAIEmbeddings

    return LangChainEmbeddingProvider(
        AzureOpenAIEmbeddings(
            azure_endpoint=endpoint,
            openai_api_key=SecretStr(api_key),
            openai_api_version=api_version,
            deployment=deployment,
            max_retries=0,
        ),
        provider_name="azure_openai",
        model_name=deployment,
    )
