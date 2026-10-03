"""LangChain-backed chat providers (AWS Bedrock Claude, Azure OpenAI).

LangChain is used here purely as a vendor-adapter layer: it normalizes message formats and
usage metadata across providers. The concrete chat model can be injected, which is how the
adapters are unit-tested without credentials (using LangChain fake chat models).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.errors import ProviderConfigurationError, ProviderError, ProviderTimeoutError
from app.providers.llm.base import LLMRequest, LLMResponse, estimate_tokens

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


class LangChainChatProvider:
    """Adapter from ``LLMProvider`` to any LangChain ``BaseChatModel``."""

    def __init__(self, chat_model: BaseChatModel, provider_name: str, model_name: str) -> None:
        self._chat_model = chat_model
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

    def generate(self, request: LLMRequest) -> LLMResponse:
        messages: list[BaseMessage] = [
            SystemMessage(content=request.system),
            HumanMessage(content=request.user),
        ]
        try:
            result = self._chat_model.invoke(messages)
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"{self._provider_name} call timed out") from exc
        except Exception as exc:  # vendor SDKs raise many unrelated exception types
            raise ProviderError(f"{self._provider_name} call failed: {type(exc).__name__}") from exc

        text = _content_to_text(result.content)
        usage: Any = getattr(result, "usage_metadata", None) or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        estimated = False
        if not input_tokens and not output_tokens:
            input_tokens = estimate_tokens(request.system + request.user)
            output_tokens = estimate_tokens(text)
            estimated = True
        metadata: Any = getattr(result, "response_metadata", None) or {}
        stop_reason = metadata.get("stopReason") or metadata.get("finish_reason")
        return LLMResponse(
            text=text,
            provider=self._provider_name,
            model_name=self._model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_estimated=estimated,
            stop_reason=str(stop_reason) if stop_reason else None,
            is_mock=False,
        )


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # Bedrock Converse may return content blocks
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


class BedrockClaudeProvider(LangChainChatProvider):
    """Anthropic Claude on AWS Bedrock via the Converse API.

    Credentials resolve through the standard AWS chain (env vars, profile, IAM role); nothing is
    read from application config beyond region and model id.
    """

    def __init__(
        self,
        model_id: str,
        region: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        chat_model: BaseChatModel | None = None,
    ) -> None:
        if chat_model is None:
            try:
                from botocore.config import Config
                from langchain_aws import ChatBedrockConverse
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise ProviderConfigurationError("langchain-aws is not installed") from exc
            chat_model = ChatBedrockConverse(
                model_id=model_id,
                region_name=region,
                temperature=temperature,
                max_tokens=max_tokens,
                # SDK-level timeouts; retries are owned by ModelGateway, so disable SDK retries.
                config=Config(
                    read_timeout=timeout_s,
                    connect_timeout=min(10.0, timeout_s),
                    retries={"max_attempts": 1},
                ),
            )
        super().__init__(chat_model, provider_name="bedrock", model_name=model_id)


class AzureOpenAIProvider(LangChainChatProvider):
    """Azure OpenAI chat deployment.

    Standard chat models get ``temperature`` and a fixed ``seed``. Reasoning models (GPT-5,
    o-series) reject both, so with ``reasoning_effort`` set they are omitted and the token budget
    is sent as ``max_completion_tokens``, which also covers the hidden reasoning tokens.
    """

    def __init__(
        self,
        endpoint: str | None,
        api_key: str | None,
        api_version: str,
        deployment: str | None,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        chat_model: BaseChatModel | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if chat_model is None:
            if not endpoint or not api_key or not deployment:
                raise ProviderConfigurationError(
                    "Azure OpenAI requires DOCINTEL_AZURE_OPENAI_ENDPOINT, "
                    "DOCINTEL_AZURE_OPENAI_API_KEY and DOCINTEL_AZURE_OPENAI_CHAT_DEPLOYMENT"
                )
            chat_model = build_azure_chat_model(
                endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
                deployment=deployment,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                reasoning_effort=reasoning_effort,
            )
        super().__init__(chat_model, provider_name="azure_openai", model_name=deployment or "azure")


def build_azure_chat_model(
    endpoint: str,
    api_key: str,
    api_version: str,
    deployment: str,
    temperature: float,
    max_tokens: int,
    timeout_s: float,
    reasoning_effort: str | None,
) -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    sampling: dict[str, Any] = (
        {"reasoning_effort": reasoning_effort}
        if reasoning_effort
        else {"temperature": temperature, "seed": 0}
    )
    return AzureChatOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        azure_deployment=deployment,
        max_tokens=max_tokens,
        timeout=timeout_s,
        max_retries=0,
        **sampling,
    )
