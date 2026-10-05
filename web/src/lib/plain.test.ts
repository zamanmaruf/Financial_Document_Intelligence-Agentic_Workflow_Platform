import { describe, expect, it } from "vitest";

import type { AuditEvent } from "@/api/client";
import { friendlyError, ApiError, humanWait } from "@/api/client";

import {
  auditText,
  confidenceWords,
  documentTypeText,
  fieldLabel,
  formatValue,
  reasonText,
  stepState,
  stepTimings,
  sureness,
} from "./plain";

function event(event_type: string, details: Record<string, unknown> = {}, actor = "system"): AuditEvent {
  return {
    event_type,
    details,
    actor,
    event_id: "evt_1",
    event_hash: "",
    prev_hash: "",
    sequence: 1,
  };
}

describe("confidence wording", () => {
  it("maps scores to words at the documented thresholds", () => {
    expect(sureness(0.95)).toBe("very");
    expect(sureness(0.9)).toBe("very");
    expect(sureness(0.8)).toBe("fairly");
    expect(sureness(0.6)).toBe("somewhat");
    expect(sureness(0.59)).toBe("not");
    expect(confidenceWords(1)).toBe("Very sure");
  });
});

describe("pipeline step state", () => {
  it("marks earlier steps done and the next one active while processing", () => {
    expect(stepState("CLASSIFIED", 0, true)).toBe("done");
    expect(stepState("CLASSIFIED", 1, true)).toBe("done");
    expect(stepState("CLASSIFIED", 2, true)).toBe("active");
    expect(stepState("CLASSIFIED", 3, true)).toBe("waiting");
  });

  it("starts with the first step active", () => {
    expect(stepState("INGESTED", 0, true)).toBe("active");
    expect(stepState("INGESTED", 0, false)).toBe("waiting");
  });

  it("treats final states as complete and failures as failed", () => {
    expect(stepState("NEEDS_REVIEW", 4, false)).toBe("done");
    expect(stepState("READY", 0, false)).toBe("done");
    expect(stepState("FAILED", 0, false, "INGESTED")).toBe("failed");
    expect(stepState("FAILED", 1, false, "TEXT_EXTRACTED")).toBe("failed");
    expect(stepState("FAILED", 0, false, "TEXT_EXTRACTED")).toBe("done");
  });
});

describe("labels", () => {
  it("humanises field names and document types", () => {
    expect(fieldLabel("amount_due")).toBe("Amount due");
    expect(fieldLabel("nav_per_share")).toBe("NAV per share");
    expect(documentTypeText("fund_summary")).toBe("Fund factsheet");
    expect(documentTypeText(null)).toBe("Not identified yet");
  });

  it("formats values", () => {
    expect(formatValue("amount_due", 5238)).toBe("5,238");
    expect(formatValue("amount_due", 12435.5)).toBe("12,435.50");
    expect(formatValue("management_fee_pct", 0.85)).toBe("0.85%");
    expect(formatValue("vendor", null)).toBe("Not found");
    expect(formatValue("vendor", "Acme")).toBe("Acme");
  });

  it("explains every review reason without jargon", () => {
    expect(reasonText("conflicting_values")).toMatch(/different values/);
    expect(reasonText("guardrail_triggered")).toMatch(/instructions aimed at AI/);
    expect(reasonText("something_new")).toBe("Something needs a closer look.");
  });
});

describe("audit trail sentences", () => {
  it("describes events in plain words", () => {
    expect(auditText(event("document.uploaded", {}, "visitor:abc"))).toBe("Document received from you");
    expect(auditText(event("workflow.transition", { to: "CLASSIFIED" }))).toBe(
      "Step finished: Type identified",
    );
    expect(auditText(event("review.approved", {}, "reviewer:abc"))).toBe("Approved by you (as reviewer)");
    expect(auditText(event("custom.thing"))).toBe("custom thing");
  });
});

describe("error wording", () => {
  it("turns limit errors into a friendly sentence with a wait time", () => {
    const err = new ApiError(429, "rate_limited", "demo limit reached: documents per day", 7200);
    expect(friendlyError(err)).toBe(
      "You've reached the demo limit (documents per day). Try again in about 2 hours.",
    );
    expect(friendlyError(new TypeError("fetch failed"))).toMatch(/connection/);
    expect(humanWait(30)).toBe("30 seconds");
    expect(humanWait(600)).toBe("10 minutes");
  });
});

describe("step timings", () => {
  const at = (type: string, seconds: number, details: Record<string, unknown> = {}): AuditEvent => ({
    ...event(type, details),
    timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, seconds)).toISOString(),
  });

  it("measures each step from the latest run's audit records", () => {
    const events = [
      at("workflow.started", 0),
      at("workflow.transition", 9, { to: "TEXT_EXTRACTED" }),
      // a re-run: only the latest workflow.started counts
      at("workflow.started", 10),
      at("workflow.transition", 11, { to: "TEXT_EXTRACTED" }),
      at("workflow.transition", 14, { to: "CLASSIFIED" }),
      at("review.created", 15),
    ];
    expect(stepTimings([...events].reverse())).toEqual({ TEXT_EXTRACTED: 1000, CLASSIFIED: 3000 });
  });

  it("returns nothing when no run has started", () => {
    expect(stepTimings([at("document.uploaded", 0)])).toEqual({});
  });
});
