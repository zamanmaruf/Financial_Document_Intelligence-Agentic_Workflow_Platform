/**
 * Plain-language wording for everything the API returns. The UI never shows raw enum values,
 * so a non-technical visitor can follow along.
 */
import type { AuditEvent, Entity, WorkflowStatus } from "@/api/client";

// --------------------------------------------------------------------------- confidence

export type Sureness = "very" | "fairly" | "somewhat" | "not";

export function sureness(confidence: number): Sureness {
  if (confidence >= 0.9) return "very";
  if (confidence >= 0.75) return "fairly";
  if (confidence >= 0.6) return "somewhat";
  return "not";
}

export const SURENESS_TEXT: Record<Sureness, string> = {
  very: "Very sure",
  fairly: "Fairly sure",
  somewhat: "Somewhat sure",
  not: "Not sure",
};

export function confidenceWords(confidence: number): string {
  return SURENESS_TEXT[sureness(confidence)];
}

// --------------------------------------------------------------------------- pipeline

export interface PipelineStep {
  status: WorkflowStatus;
  title: string;
  detail: string;
}

/** The processing steps in order, as the orchestrator records them. */
export const PIPELINE: PipelineStep[] = [
  { status: "TEXT_EXTRACTED", title: "Read", detail: "Pull the text out of the PDF" },
  { status: "CLASSIFIED", title: "Identify", detail: "Work out what kind of document it is" },
  { status: "ENTITIES_EXTRACTED", title: "Extract", detail: "Find the key figures and names" },
  { status: "VALIDATED", title: "Check", detail: "Make sure the numbers add up" },
  { status: "INDEXED", title: "Index", detail: "Prepare it for questions" },
];

const ORDER: WorkflowStatus[] = [
  "INGESTED",
  "TEXT_EXTRACTED",
  "CLASSIFIED",
  "ENTITIES_EXTRACTED",
  "VALIDATED",
  "INDEXED",
];

export const FINAL_STATUSES: ReadonlySet<WorkflowStatus> = new Set([
  "READY",
  "NEEDS_REVIEW",
  "REJECTED",
  "FAILED",
]);

export type StepState = "done" | "active" | "waiting" | "failed";

/** State of pipeline step ``index`` given the document's current status. */
export function stepState(
  status: WorkflowStatus,
  index: number,
  processing: boolean,
  failedAt?: WorkflowStatus,
): StepState {
  if (status === "FAILED") {
    const reached = failedAt ? ORDER.indexOf(failedAt) : 0;
    if (index < reached) return "done";
    return index === reached ? "failed" : "waiting";
  }
  if (FINAL_STATUSES.has(status)) return "done";
  const reached = ORDER.indexOf(status); // index of the last completed status
  if (index < reached) return "done";
  if (index === reached && processing) return "active";
  return "waiting";
}

export const STATUS_TEXT: Record<WorkflowStatus, string> = {
  INGESTED: "Received",
  TEXT_EXTRACTED: "Text read",
  CLASSIFIED: "Type identified",
  ENTITIES_EXTRACTED: "Key figures found",
  VALIDATED: "Checks done",
  INDEXED: "Ready for questions",
  READY: "Ready: all checks passed",
  NEEDS_REVIEW: "Waiting for a person to check",
  REJECTED: "Rejected by a reviewer",
  FAILED: "Couldn't be processed",
};

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

export function statusTone(status: WorkflowStatus): Tone {
  if (status === "READY") return "ok";
  if (status === "NEEDS_REVIEW") return "warn";
  if (status === "FAILED" || status === "REJECTED") return "danger";
  return "info";
}

// --------------------------------------------------------------------------- review reasons

const REASONS: Record<string, string> = {
  low_classification_confidence: "It wasn't confident about what kind of document this is.",
  unknown_document_type: "This isn't one of the document types it knows how to read.",
  low_extraction_confidence: "It wasn't confident about some of the figures.",
  schema_validation_failed: "The extracted data wasn't in the expected shape.",
  validation_rule_failed: "The numbers don't add up the way they should.",
  conflicting_values: "The document shows different values for the same figure.",
  missing_required_fields: "Some required details are missing from the document.",
  unverified_evidence: "Some values couldn't be found word-for-word in the document.",
  insufficient_evidence: "The document doesn't contain enough information to answer.",
  weak_grounding: "Parts of the answer couldn't be matched to the document.",
  low_answer_confidence: "It wasn't confident in the answer.",
  guardrail_triggered: "The document contains instructions aimed at AI systems.",
  retries_exhausted: "The AI service didn't respond properly after several tries.",
  ocr_unavailable: "The PDF is a scanned image and no text reader was available.",
  ocr_used: "The PDF is a scanned image; text read from images is double-checked by a person.",
};

export function reasonText(reason: string): string {
  return REASONS[reason] ?? "Something needs a closer look.";
}

// --------------------------------------------------------------------------- fields

const FIELD_LABELS: Record<string, string> = {
  nav_per_share: "NAV per share",
  net_asset_value: "Net asset value",
  ytd_return_pct: "Year-to-date return",
  management_fee_pct: "Management fee",
  account_number_masked: "Account number (masked)",
  shareholders_equity: "Shareholders' equity",
  tax: "Tax",
};

export function fieldLabel(name: string): string {
  const known = FIELD_LABELS[name];
  if (known) return known;
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const DOC_TYPES: Record<string, string> = {
  income_statement: "Income statement",
  balance_sheet: "Balance sheet",
  invoice: "Invoice",
  bank_statement: "Bank statement",
  fund_summary: "Fund factsheet",
  unknown: "Not a supported type",
};

export function documentTypeText(type: string | null | undefined): string {
  return type ? (DOC_TYPES[type] ?? type) : "Not identified yet";
}

export function formatValue(name: string, value: Entity["value"]): string {
  if (value === null || value === undefined || value === "") return "Not found";
  if (typeof value === "number") {
    const pct = name.endsWith("_pct");
    const formatted = value.toLocaleString("en-US", {
      // amounts with cents read as money (1,985.50), whole amounts stay whole
      minimumFractionDigits: !pct && !Number.isInteger(value) ? 2 : 0,
      maximumFractionDigits: 4,
    });
    return pct ? `${formatted}%` : formatted;
  }
  return value;
}

export const VALIDATION_TEXT: Record<Entity["validation_status"], string> = {
  valid: "Found in the document",
  unverified: "Couldn't confirm in the document",
  missing: "Not in the document",
  invalid: "Failed a check",
  conflict: "Document shows different values",
  corrected: "Corrected by a person",
};

export function validationTone(status: Entity["validation_status"]): Tone {
  if (status === "valid" || status === "corrected") return "ok";
  if (status === "missing") return "neutral";
  if (status === "invalid") return "danger";
  return "warn";
}

// --------------------------------------------------------------------------- audit trail

function actorText(actor: string): string {
  if (actor.startsWith("visitor:")) return "you";
  if (actor.startsWith("reviewer:")) return "you (as reviewer)";
  if (actor === "system") return "the system";
  return actor;
}

function detail(event: AuditEvent, key: string): unknown {
  return event.details?.[key];
}

export function auditText(event: AuditEvent): string {
  const who = actorText(event.actor);
  switch (event.event_type) {
    case "document.uploaded":
      return `Document received from ${who}`;
    case "document.duplicate_upload":
      return "The same file was uploaded again; the existing copy was reused";
    case "workflow.started":
      return `Processing started by ${who}`;
    case "workflow.transition": {
      const to = detail(event, "to");
      return typeof to === "string" && to in STATUS_TEXT
        ? `Step finished: ${STATUS_TEXT[to as WorkflowStatus]}`
        : "Moved to the next step";
    }
    case "workflow.completed":
      return "Processing finished";
    case "guardrail.document_injection_suspected":
      return "Hidden instructions aimed at AI were detected";
    case "guardrail.question_blocked":
      return "A question was blocked by the safety rules";
    case "review.created":
      return "Sent to a person for review";
    case "review.approved":
      return `Approved by ${who}`;
    case "review.rejected":
      return `Rejected by ${who}`;
    case "review.corrected":
      return `Corrected by ${who}`;
    case "review.superseded":
      return "An older review was replaced by a new run";
    case "answer.generated":
      return "A question was answered";
    default:
      return event.event_type.replace(/[._]/g, " ");
  }
}

export function shortHash(hash: string): string {
  return hash ? `${hash.slice(0, 8)}…${hash.slice(-4)}` : "";
}
