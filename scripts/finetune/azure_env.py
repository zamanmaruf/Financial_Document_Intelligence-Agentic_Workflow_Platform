"""Azure OpenAI credentials for the fine-tuning scripts, from the environment or .env.

The fine-tuning resource is read from DOCINTEL_FINETUNE_AZURE_* and falls back to the main
DOCINTEL_AZURE_OPENAI_* resource. Values are returned to the caller and never printed.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_VERSION = "2024-10-21"


def env(*names: str) -> str | None:
    from dotenv import dotenv_values

    path = ROOT / ".env"
    file_values = dotenv_values(path) if path.exists() else {}
    for name in names:
        value = os.environ.get(name) or file_values.get(name)
        if value:
            return value
    return None


def azure_credentials(resource: str) -> tuple[str, str, str]:
    """(endpoint, api_key, api_version) for ``resource`` = "main" or "finetune"."""
    if resource == "finetune":
        endpoint = env("DOCINTEL_FINETUNE_AZURE_ENDPOINT", "DOCINTEL_AZURE_OPENAI_ENDPOINT")
        key = env("DOCINTEL_FINETUNE_AZURE_API_KEY", "DOCINTEL_AZURE_OPENAI_API_KEY")
        version = env("DOCINTEL_FINETUNE_AZURE_API_VERSION") or DEFAULT_API_VERSION
    else:
        endpoint = env("DOCINTEL_AZURE_OPENAI_ENDPOINT")
        key = env("DOCINTEL_AZURE_OPENAI_API_KEY")
        version = env("DOCINTEL_AZURE_OPENAI_API_VERSION") or DEFAULT_API_VERSION
    if not endpoint or not key:
        raise SystemExit(f"Azure OpenAI endpoint or key for the {resource} resource is not set")
    return endpoint, key, version
