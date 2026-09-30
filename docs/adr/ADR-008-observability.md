# ADR-008: Observability design

- Status: Accepted
- Date: 2026-09-30

## Context

AI systems fail in ways plain HTTP metrics do not show: rising review rates, falling groundedness,
cost spikes, a silently changed model version. Operators need request-level traces for incidents and
aggregate signals for trends, without cloud dependencies locally and without leaking sensitive data.

## Decision

**Structured JSON logs** (`app/observability/logging.py`):

- context variables propagate `request_id` (from `X-Request-ID` or generated, echoed in responses),
  `document_id` and `workflow_id` into every log line;
- event-specific fields: `model_provider`, `model_name`, `prompt_name`, `prompt_version`,
  `prompt_hash`, `embedding_model`, `latency_ms`, `input_tokens`, `output_tokens`,
  `tokens_estimated`, `estimated_cost`, `retry_count`, `retrieval_top_k`, `retrieval_scores`,
  `validation_result`, `review_required`, `error_type`, `is_mock`;
- **redaction in the formatter**: emails, IBANs and 8+ digit account numbers are masked, and keys
  that look like secrets are replaced with `[REDACTED]`. Question text is not logged (length and hash
  only).

**Metrics** (`app/observability/metrics.py`):

- `MetricsRecorder` protocol (`increment`, `observe`, `snapshot`);
- `InMemoryMetrics` (default) exposes `GET /metrics` as JSON (count, sum, avg, p50, p95, max per label
  set) or Prometheus text (`?format=prometheus`);
- `OpenTelemetryMetrics` forwards to the OTel API as well, so an OTLP exporter can ship to CloudWatch
  (ADOT collector), Azure Monitor / Application Insights, or Prometheus without code changes. Exporter
  configuration is deployment-specific and **not** included.

**Model invocation ledger**: every LLM call is persisted as a `ModelInvocation` (provider, model,
prompt version and hash, tokens, estimated cost, latency, retries, success, error type). This feeds
drift and cost analysis.

**Cost**: `config/pricing.yaml` holds illustrative per-1K-token prices; unknown models cost 0 and are
reported as unknown. Mock-mode tokens are estimates (characters / 4) and flagged `tokens_estimated`.

**Audit trail** (separate from logs, see ADR-009): an append-only, hash-chained business event log.

## Consequences

- Local mode shows meaningful metrics with no external services.
- In-memory metrics reset on restart and are per-process; production should rely on the OTel export
  path.
- Tracing (spans) is not implemented; request, document and workflow ids give correlation today. OTel
  tracing is on the roadmap.
