# ADR-007: Human-in-the-loop (HITL) strategy

- Status: Accepted
- Date: 2026-09-30

## Context

Model outputs used for financial operations must be reviewable, and uncertain outputs must not flow
downstream unchecked. Reviewers need to understand *why* something was escalated and to fix it
efficiently. Their decisions must be attributable.

## Decision

**Routing rules** (deterministic, configurable thresholds). Each rule maps to a `ReviewReason`:

| Reason | Trigger |
|---|---|
| `unknown_document_type` / `low_classification_confidence` | classifier returns unknown or confidence below 0.70 |
| `low_extraction_confidence` | mean field confidence below 0.60 (unverified evidence is penalised) |
| `missing_required_fields` | a required schema field is absent |
| `validation_rule_failed` | accounting identity or format rule fails (balance sheet, invoice total, bank reconciliation, ...) |
| `conflicting_values` | the same field appears with different values in the document |
| `unverified_evidence` | the model's evidence snippet or value is not found in the page text |
| `guardrail_triggered` | prompt-injection patterns in the document, or prohibited language in an answer |
| `ocr_used` / `ocr_unavailable` | text came from OCR, or a scanned PDF could not be read |
| `retries_exhausted` | model call failed after bounded retries |
| `insufficient_evidence` / `weak_grounding` / `low_answer_confidence` | RAG answer could not be supported |

**One case per workflow run** with all reasons and human-readable details, the original model output,
and the model and prompt versions that produced it. Re-processing a document supersedes its pending
cases (`superseded`), so reviewers never act on stale output.

**Decisions** (`app/human_review/service.py`):

- `approve`: document `NEEDS_REVIEW -> READY`.
- `reject`: document `NEEDS_REVIEW -> REJECTED` (no longer queryable).
- `correct`:
  - field corrections are coerced (amounts, currency, masked account), validated against the schema
    **and** field format rules, and saved as a **new extraction version** with
    `corrected_by_review_id`. The previous version is kept, corrected fields get status `corrected`
    and confidence 1.0, cross-field validation re-runs, and the document moves to `READY`;
  - a `document_type` correction on its own triggers re-processing with the reviewer's type;
  - answer reviews accept a corrected answer text.
- A case can be resolved once; every decision is audited with the reviewer identity. With API-key
  auth enabled, the identity comes from the credential, not from the request body.

## Alternatives considered

- **Per-field review tasks**: finer-grained, but more queue noise for small documents. One case per
  run with field-level details is simpler for this scope.
- **Confidence-only routing**: model self-reported confidence is not calibrated. Deterministic checks
  (validation, evidence, groundedness) carry most of the routing weight.

## Consequences

- Review volume depends on thresholds; the drift monitor tracks review, rejection and correction
  rates to catch threshold or model problems.
- Corrections form a labelled dataset (original vs corrected values) usable for evaluation and for
  any future fine-tuning experiment (`docs/fine-tuning-pathway.md`).
- Not implemented: reviewer assignment, SLAs, four-eyes approval, and a review UI (API only). These
  are on the roadmap.
