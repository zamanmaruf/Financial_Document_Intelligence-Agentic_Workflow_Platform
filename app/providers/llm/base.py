"""LLM provider interface.

Business logic depends only on ``LLMProvider``. Concrete providers (Bedrock, Azure OpenAI, mock)
translate an ``LLMRequest`` to a vendor call and return a normalized ``LLMResponse``.
"""

from __future__ import annotations

import base64
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.core.hashing import sha256_bytes

# Used only when a provider reports no usage; real image costs depend on size and model.
IMAGE_TOKEN_ESTIMATE = 1600


class ImageInput(BaseModel):
    """An image sent with the user message (for example a rendered page for vision OCR)."""

    data_base64: str
    mime_type: Literal["image/png", "image/jpeg"] = "image/png"
    sha256: str

    @classmethod
    def from_bytes(
        cls, data: bytes, mime_type: Literal["image/png", "image/jpeg"] = "image/png"
    ) -> ImageInput:
        return cls(
            data_base64=base64.b64encode(data).decode("ascii"),
            mime_type=mime_type,
            sha256=sha256_bytes(data),
        )

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.data_base64}"


class LLMRequest(BaseModel):
    system: str
    user: str
    temperature: float = 0.0
    max_tokens: int = 1024
    prompt_name: str
    prompt_version: str
    # The structured variables the prompt was rendered from. Real providers ignore this; the
    # deterministic mock provider uses it instead of re-parsing the rendered prompt text.
    variables: dict[str, Any] = Field(default_factory=dict)
    images: list[ImageInput] = Field(default_factory=list)


class LLMResponse(BaseModel):
    text: str
    provider: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_estimated: bool = False
    stop_reason: str | None = None
    is_mock: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Single completion. Implementations raise ``ProviderError`` subclasses on failure."""
        ...


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) used only when a provider reports no usage."""
    return max(1, len(text) // 4)
