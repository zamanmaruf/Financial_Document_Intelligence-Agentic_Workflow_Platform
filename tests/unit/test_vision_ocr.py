"""Vision OCR: image plumbing through the LLM adapters and gateway, the extractor, and wiring."""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from PIL import Image
from pydantic import SecretStr

from app.core.config import LLMProviderName, OCRProviderName
from app.core.errors import ProviderConfigurationError, ProviderError
from app.domain.enums import TextExtractionMethod
from app.observability.cost import CostEstimator
from app.observability.metrics import InMemoryMetrics
from app.prompts.registry import PromptRegistry
from app.providers import factory
from app.providers.llm.base import ImageInput, LLMRequest, LLMResponse
from app.providers.llm.langchain_chat import (
    AzureOpenAIProvider,
    BedrockClaudeProvider,
    build_azure_chat_model,
)
from app.providers.ocr.tesseract import TesseractOCRExtractor
from app.providers.ocr.vision_llm import (
    PageTranscriptionLLMOutput,
    VisionLLMOCRExtractor,
    number_disagreement,
)
from app.services.container import build_container
from app.services.model_gateway import ModelGateway
from tests.support import NO_RETRY_DELAY, ROOT, make_settings, sample_pdf

PNG = b"\x89PNG\r\n\x1a\n-not-a-real-image"


class _CapturingChatModel(GenericFakeChatModel):
    seen: list[list[BaseMessage]] = []

    def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
        self.seen.append(list(input))
        return super().invoke(input, *args, **kwargs)


class ScriptedVisionProvider:
    """Returns one canned transcription per call and keeps every request."""

    def __init__(self, pages: list[list[str]], fail: bool = False) -> None:
        self.pages = pages
        self.fail = fail
        self.requests: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return "bedrock"

    @property
    def model_name(self) -> str:
        return "anthropic.claude-haiku-4-5-20251001-v1:0"

    @property
    def is_mock(self) -> bool:
        return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail:
            raise ProviderError("bedrock call failed: ThrottlingException")
        lines = self.pages[min(len(self.requests), len(self.pages)) - 1]
        return LLMResponse(
            text=json.dumps({"lines": lines}),
            provider=self.provider_name,
            model_name=self.model_name,
            input_tokens=1700,
            output_tokens=90,
        )


class FixedReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sizes: list[tuple[int, int]] = []

    def read_image(self, image: Image.Image) -> str:
        self.sizes.append(image.size)
        return self.text


class _Sink:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    def save(self, inv: Any) -> None:
        self.saved.append(inv)


def gateway(provider: Any, sink: _Sink | None = None) -> ModelGateway:
    return ModelGateway(
        provider=provider,
        prompts=PromptRegistry.load(ROOT / "prompts"),
        invocations=sink or _Sink(),
        metrics=InMemoryMetrics(),
        cost=CostEstimator.load(ROOT / "config"),
        retry_policy=NO_RETRY_DELAY,
    )


INVOICE_LINES = [
    "INVOICE",
    "Invoice Number: SCN-7781",
    "Amount Due: 1,080.00",
]


def vision_request() -> LLMRequest:
    return LLMRequest(
        system="s",
        user="transcribe",
        prompt_name="ocr.page_transcription",
        prompt_version="1.0.0",
        images=[ImageInput.from_bytes(PNG)],
    )


class TestImageInput:
    def test_hash_and_data_url(self) -> None:
        image = ImageInput.from_bytes(PNG)
        assert base64.b64decode(image.data_base64) == PNG
        assert image.data_url.startswith("data:image/png;base64,")
        assert len(image.sha256) == 64
        assert image.sha256 == ImageInput.from_bytes(PNG).sha256


class TestAdaptersSendImages:
    def test_bedrock_message_carries_text_then_image_blocks(self) -> None:
        chat = _CapturingChatModel(messages=iter([AIMessage(content='{"lines": []}')]))
        chat.seen = []
        provider = BedrockClaudeProvider(
            model_id="m", region="us-east-1", temperature=0, max_tokens=64, timeout_s=5,
            chat_model=chat,
        )  # fmt: skip
        provider.generate(vision_request())
        human = chat.seen[0][1]
        assert human.content == [
            {"type": "text", "text": "transcribe"},
            {"type": "image_url", "image_url": {"url": ImageInput.from_bytes(PNG).data_url}},
        ]

    def test_bedrock_converse_receives_native_image_bytes(self) -> None:
        from langchain_aws.chat_models.bedrock_converse import _messages_to_bedrock

        from app.providers.llm.langchain_chat import _human_message

        messages, _system = _messages_to_bedrock([_human_message(vision_request())])
        content = messages[0]["content"]
        assert content[0] == {"text": "transcribe"}
        assert content[1] == {"image": {"format": "png", "source": {"bytes": PNG}}}

    def test_azure_payload_contains_image_url_part(self) -> None:
        from app.providers.llm.langchain_chat import _human_message

        model = build_azure_chat_model(
            endpoint="https://example.openai.azure.com",
            api_key="not-a-real-key",
            api_version="2025-04-01-preview",
            deployment="gpt-4.1-mini",
            temperature=0.0,
            max_tokens=4096,
            timeout_s=5,
            reasoning_effort=None,
        )
        payload: dict[str, Any] = model._get_request_payload([_human_message(vision_request())])  # type: ignore[attr-defined]
        parts = payload["messages"][0]["content"]
        assert parts[0] == {"type": "text", "text": "transcribe"}
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_estimated_tokens_count_images(self) -> None:
        provider = AzureOpenAIProvider(
            endpoint=None, api_key=None, api_version="2024-06-01", deployment="d",
            temperature=0, max_tokens=64, timeout_s=5,
            chat_model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        )  # fmt: skip
        response = provider.generate(vision_request())
        assert response.tokens_estimated
        assert response.input_tokens >= 1600


class TestGateway:
    def test_image_hashes_are_logged_not_image_bytes(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = ScriptedVisionProvider([INVOICE_LINES])
        image = ImageInput.from_bytes(PNG)
        with caplog.at_level(logging.INFO, logger="app.services.model_gateway"):
            result = gateway(provider).invoke(
                "ocr.page_transcription",
                render_vars={"page_number": 1, "page_count": 1},
                schema=PageTranscriptionLLMOutput,
                operation="ocr",
                images=[image],
            )
        assert result.output.lines == INVOICE_LINES
        assert provider.requests[0].images == [image]
        fields = [getattr(r, "fields", {}) for r in caplog.records]
        logged = [f for f in fields if f.get("event") == "model_invocation"]
        assert logged and logged[0]["image_sha256"] == [image.sha256]
        assert image.data_base64 not in caplog.text


class TestVisionExtractor:
    def test_pages_are_rendered_capped_and_transcribed(self) -> None:
        provider = ScriptedVisionProvider([INVOICE_LINES])
        sink = _Sink()
        extractor = VisionLLMOCRExtractor(gateway(provider, sink), max_edge_px=800)
        text = extractor.extract(sample_pdf("edge_scanned_invoice.pdf"))

        assert text.method == TextExtractionMethod.OCR_VISION_LLM
        assert text.pages[0].text == "\n".join(INVOICE_LINES)
        assert len(provider.requests) == len(text.pages) >= 1
        first = provider.requests[0]
        assert first.prompt_name == "ocr.page_transcription"
        assert first.variables == {"page_number": 1, "page_count": len(text.pages)}
        image = Image.open(io.BytesIO(base64.b64decode(first.images[0].data_base64)))
        assert image.format == "PNG"
        assert max(image.size) in (799, 800)  # pdfium rounds the scaled size
        assert sink.saved[0].operation == "ocr"
        assert extractor.name == "bedrock vision"
        assert text.warnings == []

    def test_cross_check_flags_numbers_the_engines_disagree_on(self) -> None:
        reader = FixedReader("INVOICE\nInvoice Number: SCN-7781\nAmount Due: 1,086.00")
        extractor = VisionLLMOCRExtractor(
            gateway(ScriptedVisionProvider([INVOICE_LINES])), max_edge_px=800, cross_check=reader
        )
        text = extractor.extract(sample_pdf("edge_scanned_invoice.pdf"))
        assert len(text.warnings) == len(text.pages)
        warning = text.warnings[0]
        assert warning.startswith("page 1: bedrock vision and Tesseract read different numbers")
        assert "Only the vision model read: 1080" in warning
        assert "Only Tesseract read: 1086" in warning
        assert max(reader.sizes[0]) in (799, 800)  # Tesseract reads the same image

    def test_cross_check_is_silent_when_numbers_agree(self) -> None:
        reader = FixedReader("INVOICE Invoice Number SCN-7781 Amount Due 1,080.00")
        extractor = VisionLLMOCRExtractor(
            gateway(ScriptedVisionProvider([INVOICE_LINES])), max_edge_px=800, cross_check=reader
        )
        assert extractor.extract(sample_pdf("edge_scanned_invoice.pdf")).warnings == []

    def test_provider_failures_propagate(self) -> None:
        extractor = VisionLLMOCRExtractor(gateway(ScriptedVisionProvider([], fail=True)))
        with pytest.raises(ProviderError):
            extractor.extract(sample_pdf("edge_scanned_invoice.pdf"))

    def test_number_disagreement_uses_canonical_numbers(self) -> None:
        assert number_disagreement("Total 1,080.00", "Total 1080") == ([], [])
        assert number_disagreement("a 55 b 77", "a 55 b 71") == (["77"], ["71"])
        assert number_disagreement("item 1 of 2", "item 7 of 2") == ([], [])  # single digits


class TestWiring:
    def test_bedrock_vision_uses_claude_with_its_own_budget(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path, ocr_provider=OCRProviderName.BEDROCK_VISION, ocr_vision_max_tokens=3000
        )
        provider = factory.build_vision_llm_provider(settings)
        assert isinstance(provider, BedrockClaudeProvider)
        assert provider.model_name == settings.bedrock_model_id
        chat: Any = provider._chat_model
        assert chat.max_tokens == 3000
        override = make_settings(
            tmp_path, ocr_provider=OCRProviderName.BEDROCK_VISION, ocr_vision_model="vision-m"
        )
        assert factory.build_vision_llm_provider(override).model_name == "vision-m"

    def test_azure_vision_uses_the_configured_deployment(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path,
            ocr_provider=OCRProviderName.AZURE_VISION,
            azure_openai_endpoint="https://example.openai.azure.com",
            azure_openai_api_key=SecretStr("not-a-real-key"),
            azure_openai_chat_deployment="chat-deploy",
            ocr_vision_model="vision-deploy",
        )
        provider = factory.build_vision_llm_provider(settings)
        assert isinstance(provider, AzureOpenAIProvider)
        assert provider.model_name == "vision-deploy"

    def test_azure_vision_requires_endpoint_key_and_deployment(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="azure_vision requires"):
            make_settings(tmp_path, ocr_provider=OCRProviderName.AZURE_VISION)

    def test_vision_ocr_is_refused_in_demo_mode(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not available in demo mode"):
            make_settings(
                tmp_path,
                ocr_provider=OCRProviderName.BEDROCK_VISION,
                demo_mode=True,
                demo_secret=SecretStr("x" * 40),
            )

    def test_non_vision_settings_have_no_vision_model(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigurationError):
            factory.build_vision_llm_provider(make_settings(tmp_path))

    def test_extractor_needs_a_gateway(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, ocr_provider=OCRProviderName.BEDROCK_VISION)
        with pytest.raises(ProviderConfigurationError):
            factory.build_ocr_extractor(settings)

    def test_container_builds_vision_ocr_offline(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path,
            llm_provider=LLMProviderName.MOCK,
            ocr_provider=OCRProviderName.BEDROCK_VISION,
        )
        c = build_container(settings, retry_policy=NO_RETRY_DELAY)
        try:
            ocr = c.text_extraction.ocr
            assert isinstance(ocr, VisionLLMOCRExtractor)
            assert ocr.name == "bedrock vision"
            assert c.gateway.provider.is_mock  # the document pipeline keeps its own model
            tesseract_installed = TesseractOCRExtractor().is_available()
            assert (c.pages._ocr is not None) == tesseract_installed  # click-to-locate boxes
        finally:
            c.close()
