"""Loader for ``config/document_types.yaml`` (classifier keywords + extractor label synonyms)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.domain.enums import DocumentType


class DocumentTypeConfig(BaseModel):
    description: str
    keywords: dict[str, float] = Field(default_factory=dict)
    labels: dict[str, list[str]] = Field(default_factory=dict)


class DocumentTypeRegistry(BaseModel):
    version: str
    document_types: dict[DocumentType, DocumentTypeConfig]

    @classmethod
    def load(cls, config_dir: Path) -> DocumentTypeRegistry:
        path = config_dir / "document_types.yaml"
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(data)

    def get(self, document_type: DocumentType) -> DocumentTypeConfig | None:
        return self.document_types.get(document_type)
