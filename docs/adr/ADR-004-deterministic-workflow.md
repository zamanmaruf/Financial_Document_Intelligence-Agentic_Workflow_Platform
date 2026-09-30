# ADR-004: Deterministic workflow vs autonomous agents

- Status: Accepted
- Date: 2026-09-30

## Context

"Agentic workflow" can mean anything from a fixed pipeline with model calls at some steps to an
autonomous agent that chooses tools in a loop. In regulated financial services, every processing path
must be explainable to auditors and reproducible for incident review, and the system must bound what
an LLM can cause to happen.

## Decision

Implement the document workflow as an **explicit state machine with LLM-powered steps**, not an
autonomous agent.

```
INGESTED -> TEXT_EXTRACTED -> CLASSIFIED -> ENTITIES_EXTRACTED -> VALIDATED -> INDEXED -> READY
                                                                                       \-> NEEDS_REVIEW -> READY | REJECTED
any step -> FAILED        READY | REJECTED | FAILED | NEEDS_REVIEW -> INGESTED (reprocess)
```

- `ALLOWED_TRANSITIONS` in `app/workflows/state_machine.py` is the single source of truth; illegal
  transitions raise `IllegalTransitionError`.
- Every transition is persisted on the `WorkflowState` history and written to the hash-chained audit
  log.
- The model **proposes** (a document type, field values, an answer). Deterministic code **decides**:
  confidence thresholds, validation rules, evidence verification, groundedness and guardrails decide
  whether the output is accepted or routed to a human.
- Soft failures (low confidence, validation errors, model outage after retries, OCR use,
  injection-suspected content) do not stop the pipeline. They accumulate as `ReviewReason`s and
  produce **one** review case with all reasons. Hard failures (empty or corrupt PDF, vector-store
  outage) move the document to `FAILED` with an `error_type`; the document can then be retried.
- The LLM has **no tools**: it cannot call APIs, change state, approve payments or trigger
  side-effects. This neutralises most of the impact of prompt injection.

## Where this is still "agentic"

The system performs multi-step reasoning tasks autonomously (classify, extract with evidence, answer
with citations) and escalates when uncertain. That is the useful part of agentic behaviour for
document operations, with a bounded action space.

## Alternatives considered

- **ReAct / tool-calling agent** choosing the next step: flexible, but paths become non-enumerable,
  cost and latency are unbounded, and failures are hard to reproduce.
- **LangGraph** graph with checkpoints: a good future fit if steps become parallel or long-running
  (see ADR-001). The transition table maps directly onto graph nodes.

## Consequences

- Processing paths can be enumerated in tests (`tests/unit/test_gateway_observability_audit.py::TestStateMachine`,
  `tests/integration/test_workflow_samples.py`).
- Adding a step is a code change with review, not a prompt change.
- Processing is synchronous inside the API request; see ADR-008 and the roadmap for moving it to a
  queue worker.
