.PHONY: install dev test test-unit test-integration test-e2e lint format typecheck eval gate \
        drift drift-baseline baseline data docker docker-run demo lock clean check \
        web web-dev web-check web-e2e demo-site deploy deploy-cd-bootstrap smoke-live ocr-compare

VENV ?= .venv
PY := $(VENV)/bin/python
IMAGE ?= fin-docintel:local

# `uv` is used when available; falls back to the standard venv + pip toolchain.
install:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --python 3.12 $(VENV) && uv pip install --python $(PY) -e ".[dev,llamaindex]"; \
	else \
		python3.12 -m venv $(VENV) && $(PY) -m pip install --upgrade pip && $(PY) -m pip install -e ".[dev,llamaindex]"; \
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

# Cloud engines need credentials: OCR_ENGINES=tesseract,bedrock_vision,azure_vision
OCR_ENGINES ?= tesseract
ocr-compare:
	$(PY) scripts/ocr_compare.py --engines $(OCR_ENGINES) --output reports/ocr_compare.json

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

# --- public demo site (web/) -------------------------------------------------------------------
web:
	cd web && npm ci && npm run build

# Vite dev server on :5173, proxying the API on :8000 (run `make demo-site` in another terminal).
web-dev:
	cd web && npm run dev

web-check:
	cd web && npm run lint && npm run typecheck && npm test && npm run build

# Browser tests against a demo-mode API started by Playwright (needs `make web` first).
web-e2e:
	cd web && npx playwright test

# API in demo mode with the offline engine, serving web/dist at http://127.0.0.1:8000/.
demo-site:
	DOCINTEL_DEMO_MODE=true DOCINTEL_DEMO_COOKIE_SECURE=false \
	DOCINTEL_LLM_PROVIDER=mock DOCINTEL_EMBEDDING_PROVIDER=hashing \
	DOCINTEL_DEMO_SECRET=$$(openssl rand -hex 32) \
	$(PY) -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000

# Build, push and deploy to AWS (see deploy/aws/RUNBOOK.md). Requires ALERT_EMAIL.
deploy:
	deploy/aws/deploy.sh

# One-off, with an admin profile: the GitHub OIDC provider and the roles the deploy workflow uses.
deploy-cd-bootstrap:
	aws cloudformation deploy --stack-name docintel-github-deploy \
		--template-file deploy/aws/github-oidc.yaml --capabilities CAPABILITY_NAMED_IAM \
		--no-fail-on-empty-changeset
	@aws cloudformation describe-stacks --stack-name docintel-github-deploy \
		--query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output text

# Smoke tests against the deployed site with real AI (about $0.02 a run; at most about once an
# hour per IP), then read-only AWS checks when credentials are available. Override LIVE_URL.
LIVE_URL ?= https://d1cpufi9ii8q1y.cloudfront.net
smoke-live:
	cd web && LIVE_URL=$(LIVE_URL) npx playwright test -c playwright.live.config.ts
	@if aws sts get-caller-identity >/dev/null 2>&1; then deploy/aws/smoke.sh; \
	else echo "No AWS credentials: skipping the AWS-side checks (deploy/aws/smoke.sh)"; fi

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache reports data htmlcov .coverage
