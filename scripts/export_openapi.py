"""Write the API's OpenAPI schema (with demo routes) for the web client's type generation.

Usage: python scripts/export_openapi.py [output]   (default: web/openapi.json)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.main import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web" / "openapi.json"
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            data_dir=Path(tmp),
            demo_mode=True,
            demo_secret="x" * 32,  # schema export only; never used to sign anything
        )
        schema = create_app(settings).openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


if __name__ == "__main__":
    main()
