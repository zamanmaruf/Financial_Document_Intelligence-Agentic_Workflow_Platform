from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ProviderConfigurationError
from app.core.registry import DocumentTypeRegistry
from app.domain.enums import DocumentType
from app.extraction.schemas import SCHEMAS, field_specs
from app.prompts.registry import PromptRegistry, PromptSpec
from tests.support import ROOT

PROMPTS_DIR = ROOT / "prompts"
HASH_LOCK = Path(__file__).resolve().parents[1] / "fixtures" / "prompt_hashes.json"


@pytest.fixture(scope="module")
def prompts() -> PromptRegistry:
    return PromptRegistry.load(PROMPTS_DIR)


class TestPromptRegistry:
    def test_all_required_categories_present(self, prompts: PromptRegistry) -> None:
        names = {p["name"] for p in prompts.catalog()}
        for category in ("classification", "extraction", "rag", "validation"):
            assert any(n.startswith(f"{category}.") for n in names), category
            assert (PROMPTS_DIR / category).is_dir()

    def test_every_prompt_has_metadata(self, prompts: PromptRegistry) -> None:
        for entry in prompts.catalog():
            spec = prompts.get(entry["name"], entry["version"])
            assert spec.name and spec.version and spec.purpose.strip()
            assert spec.output_schema

    def test_prompts_treat_content_as_untrusted(self, prompts: PromptRegistry) -> None:
        for entry in prompts.catalog():
            spec = prompts.get(entry["name"])
            system = spec.system.lower()
            assert "untrusted" in system or "ignore instructions" in system, spec.name

    def test_prompt_regression_lock(self, prompts: PromptRegistry) -> None:
        """Changing prompt text without bumping its version fails this test.

        If a prompt change is intentional: bump ``version`` in the YAML, re-run the evaluation
        suite, and add the new ``name@version`` hash to tests/fixtures/prompt_hashes.json.
        """
        locked: dict[str, str] = json.loads(HASH_LOCK.read_text())
        for entry in prompts.catalog():
            key = f"{entry['name']}@{entry['version']}"
            assert key in locked, f"new prompt version {key} is not in the hash lock file"
            assert prompts.get(entry["name"], entry["version"]).hash == locked[key], (
                f"{key} text changed without a version bump"
            )

    def test_render_substitutes_variables(self, prompts: PromptRegistry) -> None:
        system, user = prompts.get("rag.grounded_answer").render(
            question="What is the amount due?", context="[chunk_id=c1 | page=1]\nAmount Due: 5"
        )
        assert "What is the amount due?" in user
        assert "chunk_id=c1" in user
        assert system

    def test_template_variable_mismatch_rejected(self) -> None:
        with pytest.raises(ProviderConfigurationError):
            PromptSpec(
                name="x.y",
                version="1.0.0",
                purpose="p",
                input_variables=["a"],
                system="sys",
                user="{a} {b}",
                output_schema="S",
            )

    def test_latest_version_is_default(self) -> None:
        base = {
            "name": "x.y",
            "purpose": "p",
            "input_variables": ["a"],
            "system": "s",
            "output_schema": "S",
        }
        reg = PromptRegistry(
            [
                PromptSpec(version="1.2.0", user="{a} v1.2", **base),
                PromptSpec(version="1.10.0", user="{a} v1.10", **base),
            ]
        )
        assert reg.get("x.y").version == "1.10.0"
        assert reg.get("x.y", "1.2.0").version == "1.2.0"


class TestDocumentTypeRegistrySync:
    """config/document_types.yaml, extraction schemas and the DocumentType enum must agree."""

    def test_types_in_sync(self) -> None:
        registry = DocumentTypeRegistry.load(ROOT / "config")
        supported = {t.value for t in DocumentType.supported()}
        assert {t.value for t in registry.document_types} == supported
        assert {t.value for t in SCHEMAS} == supported

    def test_every_schema_field_has_labels(self) -> None:
        registry = DocumentTypeRegistry.load(ROOT / "config")
        for doc_type in DocumentType.supported():
            labels = registry.document_types[doc_type].labels
            for spec in field_specs(doc_type):
                assert labels.get(spec.name), f"{doc_type.value}.{spec.name} has no labels"

    def test_every_type_has_required_fields_and_keywords(self) -> None:
        registry = DocumentTypeRegistry.load(ROOT / "config")
        for doc_type in DocumentType.supported():
            assert any(s.required for s in field_specs(doc_type))
            assert len(registry.document_types[doc_type].keywords) >= 3
