# ADR-011: Public guided demo site

- Status: Accepted
- Date: 2026-10-03

## Context

The operator console ([ADR-010](ADR-010-operator-console.md)) makes sense to engineers. The
project also needs to be shown to people who don't read code, and ideally left running at a
public URL that anyone can open without an account. That changes the threat model. Strangers
upload files, every live model call costs money, and documents can be hostile on purpose (the
sample set includes a prompt-injection invoice).

The requirements were:

- a landing page, a guided tour and a playground in plain language, all driven by the real
  pipeline;
- live Claude on Bedrock, but with a hard ceiling on spend;
- visitors can't see each other's documents;
- one container, deployable to AWS without stored keys.

## Decision

### Opt-in demo mode

`DOCINTEL_DEMO_MODE=true` turns it on, and requires `DOCINTEL_DEMO_SECRET` (32+ characters). With
it off, the API behaves exactly as before. The `/demo` routes don't exist, and `/` still redirects
to the console.

### Visitor sessions and workspaces

- `POST /demo/session` issues a cookie `ws_<24 hex>.<issued_at>.<HMAC-SHA256>`, which is
  `HttpOnly`, `SameSite=Strict` and `Secure` (configurable for local plain-HTTP testing). It
  expires after 24 hours. The server keeps no session table, so a valid signature is the session.
- A visitor becomes a `Principal` with the **reviewer** role, scoped to their `workspace_id`. An
  API key, if present, takes precedence. With neither, the response is 401; the anonymous local
  principal is never used in demo mode.
- `workspace_id` is stored on documents, review cases and answers, and in chunk metadata.
  Deduplication is per `(workspace_id, sha256)`, so two visitors can load the same sample.
- Ownership checks return **404, not 403**, so a visitor can't probe for other visitors'
  document ids. Corpus questions add the workspace filter on the server, after any filters the
  caller sent, so the caller can't override it.
- An idempotent startup migration adds the columns and swaps the unique index on SQLite, and
  records `schema_meta.version = 2`.
- Operator endpoints (`/metrics`, `/drift/report`, `/evaluations`, `/evaluations/run`) return 403
  to visitors. `/audit/verify` stays admin-only. A per-document `GET /documents/{id}/audit/verify`
  lets visitors check their own document's records.

### Cost: a budgeted provider with a labelled fallback

`BudgetedLLMProvider` wraps the live provider. Before each call it asks `DailyBudget` for today's
spend: the sum of estimated costs of non-mock invocations since UTC midnight, from the existing
`model_invocations` table, cached for 5 seconds. Under the cap
(`DOCINTEL_DEMO_DAILY_BUDGET_USD`, default $2), the call goes to Bedrock. At or over it, the call
goes to the deterministic mock provider. The model gateway now records the provider and model
from the response that actually came back, so fallback calls are logged as mock and don't count
towards spend. `GET /demo/status` reports `ai_mode: live | offline` and the reason, and the site
shows it on every page.

### Abuse limits

An in-memory sliding-window limiter, with all limits configurable:

- per visitor per day: 6 documents (only new uploads count, so reloading a sample is free), 12
  processing runs and 25 questions;
- per IP: 5 new sessions an hour, and 120 requests a minute on the API paths;
- uploads: at most 5 MB and 10 pages in demo mode.

Exceeding a limit returns `429` with `Retry-After`. The client IP comes from `X-Forwarded-For`
only when `DOCINTEL_DEMO_TRUSTED_PROXY_HOPS` > 0. With CloudFront and an ALB in front, the value
is 2, and the app takes the address CloudFront appended. Addresses earlier in the header can be
forged by the client, so they're ignored.

### Retention

A background task runs every 15 minutes. It deletes visitor documents older than 24 hours: the
files, vector chunks and database rows (documents, page text, extractions, workflow state,
reviews and answers).
The audit trail is **kept**. It's hash-chained, so deleting events would break verification for
every later event. Kept events hold identifiers, hashes, filenames, actors, decisions (including
corrected values) and short excerpts flagged by the injection scanner, but not page text. The
site says so in plain words.

### Live progress without a queue

`POST /documents/{id}/process/background` returns `202` and runs the workflow in a two-thread
`ThreadPoolExecutor`, one job per document. The site polls `GET /documents/{id}` every 600 ms, so
each pipeline stage lights up when the state machine actually reaches it. The upload route's
blocking work moved off the event loop (`run_in_threadpool`).

### Front end: Vite + React, served by the API

- `web/` uses Vite, React 19, TypeScript (strict, `noUncheckedIndexedAccess`), Tailwind v4 and
  shadcn-style components on Radix. Fonts and icons are bundled, so there are no CDNs.
- The API client is generated from the app's OpenAPI schema (`openapi-typescript` and
  `openapi-fetch`).
- FastAPI serves the build at `/` with an SPA fallback. Hashed assets are cached as `immutable`,
  `index.html` as `no-cache`. Only files present at startup are servable, and API path prefixes
  never fall through to the site.
- The site's CSP is `script-src 'self'; style-src 'self'` with no inline script. Document text is
  only rendered as React text, and ESLint fails the build on `dangerouslySetInnerHTML`,
  `innerHTML`, `outerHTML` or `insertAdjacentHTML`.
- The Dockerfile is multi-stage: `node:22-alpine` builds the site, and the Python image serves it.

### Hosting: one Fargate task

`deploy/aws/demo-stack.yaml` runs one ARM64 Fargate task behind an ALB, which only accepts
CloudFront's origin-facing prefix list plus a secret origin header, and CloudFront for HTTPS.
The task role allows only `bedrock:InvokeModel` on the configured inference profile and its
foundation model. The session secret is in SSM. An AWS Budgets alert at $30 a month is the
backstop.

## Alternatives considered

| Option | Why not |
|---|---|
| Next.js | its static export injects inline bootstrap scripts, which would force `'unsafe-inline'` or nonces into the CSP; this site's main job is displaying hostile document text safely |
| Separate front-end hosting (S3 + CloudFront) | a second origin means CORS and cross-site cookies; serving from the API container keeps one origin, `SameSite=Strict` and one deploy |
| Accounts or magic links | friction for a portfolio demo; a signed anonymous cookie gives isolation without collecting personal data |
| Shared demo data, read-only | visitors couldn't act as reviewers or upload, which is the most convincing part of the demo |
| Redis for limits, Postgres + S3 for state | correct for production, but adds services and roughly doubles the monthly cost of a demo; the single-instance constraint is documented instead |
| Hard-stopping live AI at the cap (errors) | a broken site for the rest of the day; the labelled offline engine keeps every flow working |
| Deleting audit events with the documents | breaks the hash chain for every later event, while the events hold no page text |

## Consequences

- **Single instance by design.** Limits, the daily-spend cache and background jobs are in
  memory, and on AWS the SQLite database, vector index and files live on the task's disk.
  Scaling out or redeploying resets them, including the audit trail. The runbook says this
  plainly. Production would move state to RDS and S3 and the limits to Redis or a WAF.
- **The budget is a soft cap.** It's computed from the app's own price table and cached for a few
  seconds, so concurrent calls can overshoot it slightly, and a restart resets the day's total.
  AWS Budgets alerts but doesn't stop spend.
- **Visitors are reviewers of their own workspace.** Their corrections become the record for
  their copy of a document only.
- **Expected cost.** About $45 a month before Bedrock usage (Fargate, ALB, public IPv4
  addresses). That's more than the $25–35 first estimated, mainly because of IPv4 address
  charges and the ALB's fixed hourly price.

## Differences from the original plan

- Background processing is a separate endpoint (`POST /documents/{id}/process/background`), not a
  `?background=true` flag. This keeps the synchronous endpoint's response model unchanged.
- `GET /documents/{id}/audit/verify` was added because `/audit/verify` is admin-only and the
  tour's tamper check needs to work for visitors.
- The audit trail keeps filenames, decisions and short flagged excerpts. The plan's "no document
  text" was too strong; the accurate statement is "no page text".
- The site is served at `/` only in demo mode. Without demo mode, `/` keeps redirecting to the
  console, because the site depends on the `/demo` routes.
