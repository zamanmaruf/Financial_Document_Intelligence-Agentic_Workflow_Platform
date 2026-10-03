"""Application configuration.

All runtime configuration comes from environment variables (prefix ``DOCINTEL_``) or a
``.env`` file. Secrets are typed as ``SecretStr`` so they never appear in reprs or logs.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LLMProviderName(StrEnum):
    MOCK = "mock"
    BEDROCK = "bedrock"
    AZURE_OPENAI = "azure_openai"


class EmbeddingProviderName(StrEnum):
    HASHING = "hashing"
    BEDROCK = "bedrock"
    AZURE_OPENAI = "azure_openai"


class VectorStoreName(StrEnum):
    CHROMA = "chroma"
    MEMORY = "memory"


class OCRProviderName(StrEnum):
    AUTO = "auto"  # tesseract if the binary is installed, otherwise none
    TESSERACT = "tesseract"
    TEXTRACT = "textract"
    NONE = "none"


class MetricsBackendName(StrEnum):
    MEMORY = "memory"
    OTEL = "otel"


class Role(StrEnum):
    """Ordered roles: each role includes the permissions of the roles before it."""

    VIEWER = "viewer"  # read documents, extractions, audit, metrics; ask questions
    ANALYST = "analyst"  # + upload and process documents
    REVIEWER = "reviewer"  # + approve / reject / correct review cases
    ADMIN = "admin"  # + run evaluations, verify audit chain

    @property
    def rank(self) -> int:
        return list(Role).index(self)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCINTEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # --- storage ---------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str | None = None  # defaults to sqlite in data_dir
    prompts_dir: Path = PROJECT_ROOT / "prompts"
    config_dir: Path = PROJECT_ROOT / "config"
    sample_data_dir: Path = PROJECT_ROOT / "sample_data"
    evals_dir: Path = PROJECT_ROOT / "evals"
    eval_use_llm_judge: bool = False
    drift_baseline_path: Path = PROJECT_ROOT / "evals" / "drift_baseline.json"
    max_upload_mb: float = 20.0
    max_pages: int = 200

    # --- providers -------------------------------------------------------------
    llm_provider: LLMProviderName = LLMProviderName.MOCK
    embedding_provider: EmbeddingProviderName = EmbeddingProviderName.HASHING
    vector_store: VectorStoreName = VectorStoreName.CHROMA
    ocr_provider: OCRProviderName = OCRProviderName.AUTO
    metrics_backend: MetricsBackendName = MetricsBackendName.MEMORY

    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2  # retries after the first attempt
    llm_retry_backoff_s: float = 0.5
    llm_json_repair_attempts: int = 1

    hashing_embedding_dim: int = 512

    # AWS Bedrock
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    textract_region: str | None = None

    # Azure OpenAI
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None
    # Reasoning deployments (GPT-5, o-series) reject temperature/seed and spend output tokens on
    # hidden reasoning. Deployment names are arbitrary, so this cannot be inferred from the name.
    azure_openai_reasoning_model: bool = False
    azure_openai_reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low"
    azure_openai_reasoning_max_tokens: int = Field(default=8192, ge=256)

    # --- chunking / retrieval --------------------------------------------------
    chunk_size: int = Field(default=600, ge=100, le=8000)
    chunk_overlap: int = Field(default=80, ge=0)
    retrieval_top_k: int = Field(default=4, ge=1, le=50)
    retrieval_min_score: float = Field(default=0.12, ge=-1.0, le=1.0)
    # When a question is scoped to one document, retrieval ranks that document's chunks and the
    # evidence decision relies on the answer step + groundedness, so a lower floor applies.
    retrieval_min_score_scoped: float = Field(default=0.03, ge=-1.0, le=1.0)
    retrieval_strong_score: float = Field(default=0.5, gt=0.0, le=1.0)
    max_context_chars: int = 6000
    classification_max_chars: int = 4000

    # --- decision thresholds ---------------------------------------------------
    classification_min_confidence: float = 0.70
    extraction_min_confidence: float = 0.60
    answer_min_confidence: float = 0.55
    groundedness_min: float = 0.80
    ocr_min_chars_per_page: int = 40
    amount_tolerance_ratio: float = 0.005
    review_ocr_documents: bool = True
    review_on_insufficient_evidence: bool = True

    # --- security --------------------------------------------------------------
    ui_enabled: bool = True  # serve the static operator console at /ui
    auth_enabled: bool = False
    # JSON object mapping API key -> role, e.g. {"dev-reviewer-key": "reviewer"}
    api_keys_json: SecretStr | None = None

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("chunk_overlap must be >= 0")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.retrieval_strong_score <= self.retrieval_min_score:
            raise ValueError("retrieval_strong_score must be greater than retrieval_min_score")
        if self.azure_openai_reasoning_model and self.azure_openai_api_version[:10] < "2024-12-01":
            raise ValueError(
                "azure_openai_reasoning_model needs DOCINTEL_AZURE_OPENAI_API_VERSION "
                "2024-12-01-preview or newer (reasoning_effort is not accepted before that)"
            )
        if self.auth_enabled and not self.api_key_roles():
            raise ValueError("auth_enabled requires DOCINTEL_API_KEYS_JSON with at least one key")
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'docintel.db'}"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def is_mock_mode(self) -> bool:
        return self.llm_provider == LLMProviderName.MOCK

    def api_key_roles(self) -> dict[str, Role]:
        if self.api_keys_json is None:
            return {}
        raw: Any = json.loads(self.api_keys_json.get_secret_value())
        if not isinstance(raw, dict):
            raise ValueError("DOCINTEL_API_KEYS_JSON must be a JSON object")
        return {str(k): Role(str(v)) for k, v in raw.items()}

    def public_summary(self) -> dict[str, Any]:
        """Non-secret configuration snapshot (safe for logs, health and eval records)."""
        return {
            "app_env": self.app_env,
            "llm_provider": self.llm_provider.value,
            "embedding_provider": self.embedding_provider.value,
            "vector_store": self.vector_store.value,
            "ocr_provider": self.ocr_provider.value,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "retrieval_top_k": self.retrieval_top_k,
            "retrieval_min_score": self.retrieval_min_score,
            "retrieval_min_score_scoped": self.retrieval_min_score_scoped,
            "classification_min_confidence": self.classification_min_confidence,
            "extraction_min_confidence": self.extraction_min_confidence,
            "answer_min_confidence": self.answer_min_confidence,
            "groundedness_min": self.groundedness_min,
            "auth_enabled": self.auth_enabled,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
