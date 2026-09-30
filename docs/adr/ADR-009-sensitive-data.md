# ADR-009: Sensitive-data handling

- Status: Accepted
- Date: 2026-09-30

## Context

Financial documents contain account numbers, IBANs, names, addresses and amounts. The platform sends
document text to third-party model providers, stores documents and derived data, and logs heavily.
The brief requires sensitive-data handling without claiming regulatory certifications or overstating
guarantees.

## Decision: what is implemented

| Control | Implementation |
|---|---|
| Secrets | environment variables only (`pydantic-settings`, `SecretStr`); `.env` is gitignored; `.env.example` holds no secrets |
| Upload validation | magic bytes, extension, content type, size, page-count limits; encrypted or malformed PDFs rejected; active content (JavaScript, embedded files, launch actions) flagged |
| File storage | server-generated ids only (path traversal impossible), directory mode 0700, files 0600, atomic write (temp file, fsync, rename) |
| Masking before indexing | account numbers masked to the last 4 digits (IBANs too) **before** chunking, so the vector index never holds full numbers |
| Masking in outputs | extracted `account_number` is stored masked; evidence snippets are redacted; audit details and logs are redacted |
| Logs | formatter-level redaction; secret-like keys replaced; raw questions not logged |
| Prompt injection | regex scanning of questions (blocked) and documents (flagged, routed to review); prompts treat content as untrusted; the model has no tools; answers must cite retrieved evidence |
| Auditability | append-only audit events with a SHA-256 hash chain; `GET /audit/verify` detects modification of stored events |
| Authorization | optional API-key auth (`X-API-Key`) with viewer < analyst < reviewer < admin roles; keys compared in constant time; identities logged as key hashes; enabling auth without keys fails at startup |
| Containers | non-root user, read-only root filesystem in compose, `no-new-privileges` |

## What is *not* implemented (and must be before production)

- **Encryption at rest**: files and SQLite are protected only by filesystem permissions. Use encrypted
  volumes or object storage with SSE-KMS (AWS) or customer-managed keys (Azure), and an encrypted
  managed database.
- **TLS**: the app serves plain HTTP; terminate TLS at a load balancer or ingress and enforce HTTPS.
- **Raw text at rest**: `document_texts` stores the unmasked extracted text (needed for reprocessing
  and correction). It should be encrypted, or reprocessing should re-extract from the encrypted
  original on demand.
- **Model-provider exposure**: the extraction prompt sends full document text (including unmasked
  account numbers) to the model provider. Bedrock and Azure OpenAI state that customer prompts are not
  used for training and can be kept in-region, but this must be confirmed contractually, and data
  residency must be set by choosing the region or deployment. Pre-masking before the model call is
  possible but reduces extraction of `account_number` to the last four digits.
- **Retention**: no automatic deletion. Define retention per document class and implement deletion of
  the file, text, chunks and derived data, while keeping audit records.
- **Identity**: API keys are a baseline; production should use OIDC/SSO (Cognito, Entra ID) with
  per-tenant authorization and document-level ACLs.
- **Rate limiting and upload malware scanning**: not implemented.

## Limits of the controls

- PII masking is pattern-based and best-effort. It will miss unusual formats and does not detect
  names or addresses.
- Injection detection is heuristic. The strongest mitigation is architectural: the model cannot act,
  only propose, and deterministic checks decide.
- The audit hash chain detects modification of stored events by someone without the ability to
  recompute the chain. It is not tamper-proof against an attacker with database write access, who can
  rewrite the whole chain. Anchoring periodic chain heads in WORM storage (S3 Object Lock, Azure
  immutable blobs) closes that gap.
- **No regulatory certification or compliance status is claimed.**
