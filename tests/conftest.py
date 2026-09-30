"""Shared fixtures. Every test runs offline against isolated temp storage in mock mode."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.registry import DocumentTypeRegistry
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.mock_handlers import default_handlers
from app.services.container import Container, build_container
from tests.support import NO_RETRY_DELAY, make_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def registry(settings: Settings) -> DocumentTypeRegistry:
    return DocumentTypeRegistry.load(settings.config_dir)


@pytest.fixture
def mock_llm_factory(registry: DocumentTypeRegistry) -> Callable[..., MockLLMProvider]:
    def factory(**kwargs: Any) -> MockLLMProvider:
        return MockLLMProvider(default_handlers(registry), **kwargs)

    return factory


@pytest.fixture
def container_factory(settings: Settings) -> Iterator[Callable[..., Container]]:
    built: list[Container] = []

    def factory(**kwargs: Any) -> Container:
        kwargs.setdefault("ocr", None)
        kwargs.setdefault("retry_policy", NO_RETRY_DELAY)
        custom_settings = kwargs.pop("settings", settings)
        c = build_container(custom_settings, **kwargs)
        built.append(c)
        return c

    yield factory
    for c in built:
        c.close()


@pytest.fixture
def container(container_factory: Callable[..., Container]) -> Container:
    return container_factory()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests by directory so `-m unit|integration|e2e` works without per-test decorators."""
    for item in items:
        for tier in ("unit", "integration", "e2e"):
            if f"tests/{tier}/" in str(item.fspath).replace("\\", "/"):
                item.add_marker(getattr(pytest.mark, tier))
