.PHONY: install dev test test-unit test-integration test-e2e lint format typecheck eval gate \
        drift drift-baseline baseline data docker docker-run demo lock clean check

VENV ?= .venv
PY := $(VENV)/bin/python
IMAGE ?= fin-docintel:local

# `uv` is used when available; falls back to the standard venv + pip toolchain.
install:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --python 3.12 $(VENV) && uv pip install --python $(PY) -e ".[dev]"; \
	else \
		python3.12 -m venv $(VENV) && $(PY) -m pip install --upgrade pip && $(PY) -m pip install -e ".[dev]"; \
	fi

dev:
	$(PY) -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000

test:
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit -m "not requires_tesseract"

test-integration:
	$(PY) -m pytest tests/integration

test-e2e:
	$(PY) -m pytest tests/e2e

lint:
	$(PY) -m ruff check app scripts tests
	$(PY) -m ruff format --check app scripts tests

format:
	$(PY) -m ruff format app scripts tests
	$(PY) -m ruff check --fix app scripts tests

typecheck:
	$(PY) -m mypy app

eval:
	$(PY) scripts/run_evals.py --output reports/eval_results.json

gate: eval
	$(PY) scripts/quality_gate.py reports/eval_results.json

# Re-baseline only after reviewing an intentional metric change.
baseline:
	$(PY) scripts/run_evals.py --output reports/eval_results.json --update-baseline

drift:
	$(PY) scripts/drift_report.py --output reports/drift_report.md

drift-baseline:
	$(PY) scripts/drift_report.py --save-baseline

data:
	$(PY) scripts/generate_sample_data.py

docker:
	docker build -t $(IMAGE) .

docker-run:
	docker compose up --build

# Requires `make dev` running in another terminal.
demo:
	$(PY) scripts/demo.py

lock:
	uv pip compile pyproject.toml --universal --python-version 3.12 -o requirements.lock

check: lint typecheck test gate

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache reports data htmlcov .coverage
