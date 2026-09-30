"""Versioned prompt registry.

Prompts live as YAML files under ``prompts/<area>/<name>.v<major>.yaml`` with ``name``,
``version``, ``purpose``, ``input_variables``, ``system`` and ``user`` templates. Rendering uses
LangChain ``PromptTemplate`` (f-string syntax) with strict variable checking. Every rendered
prompt exposes ``version`` and a content ``hash`` that are recorded with each model invocation,
so any output can be traced back to the exact prompt text that produced it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field, PrivateAttr

from app.core.errors import ProviderConfigurationError
from app.core.hashing import stable_hash


class PromptSpec(BaseModel):
    name: str
    version: str
    purpose: str
    input_variables: list[str]
    system: str
    user: str
    output_schema: str | None = Field(default=None, description="Name of the expected schema")

    _system_tpl: PromptTemplate = PrivateAttr()
    _user_tpl: PromptTemplate = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        self._system_tpl = PromptTemplate.from_template(self.system)
        self._user_tpl = PromptTemplate.from_template(self.user)
        declared = set(self.input_variables)
        used = set(self._system_tpl.input_variables) | set(self._user_tpl.input_variables)
        if used != declared:
            raise ProviderConfigurationError(
                f"prompt {self.name}@{self.version}: template variables {sorted(used)} "
                f"!= declared input_variables {sorted(declared)}"
            )

    @property
    def hash(self) -> str:
        return stable_hash(
            {"name": self.name, "version": self.version, "system": self.system, "user": self.user}
        )[:16]

    def render(self, **variables: Any) -> tuple[str, str]:
        missing = set(self.input_variables) - set(variables)
        if missing:
            raise ProviderConfigurationError(
                f"prompt {self.name}@{self.version} missing variables: {sorted(missing)}"
            )
        sys_vars = {k: variables[k] for k in self._system_tpl.input_variables}
        usr_vars = {k: variables[k] for k in self._user_tpl.input_variables}
        return self._system_tpl.format(**sys_vars), self._user_tpl.format(**usr_vars)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


class PromptRegistry:
    def __init__(self, prompts: list[PromptSpec]) -> None:
        self._by_name: dict[str, dict[str, PromptSpec]] = {}
        for p in prompts:
            versions = self._by_name.setdefault(p.name, {})
            if p.version in versions:
                raise ProviderConfigurationError(f"duplicate prompt {p.name}@{p.version}")
            versions[p.version] = p

    @classmethod
    def load(cls, prompts_dir: Path) -> PromptRegistry:
        specs: list[PromptSpec] = []
        for path in sorted(prompts_dir.rglob("*.yaml")):
            with path.open("r", encoding="utf-8") as fh:
                specs.append(PromptSpec.model_validate(yaml.safe_load(fh)))
        if not specs:
            raise ProviderConfigurationError(f"no prompts found in {prompts_dir}")
        return cls(specs)

    def get(self, name: str, version: str | None = None) -> PromptSpec:
        versions = self._by_name.get(name)
        if not versions:
            raise ProviderConfigurationError(f"unknown prompt '{name}'")
        if version is None:
            return versions[max(versions, key=_version_key)]
        if version not in versions:
            raise ProviderConfigurationError(f"unknown prompt version {name}@{version}")
        return versions[version]

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"name": p.name, "version": p.version, "purpose": p.purpose, "hash": p.hash}
            for versions in self._by_name.values()
            for p in versions.values()
        ]
