import { Check, Loader2, X } from "lucide-react";

import type { WorkflowStatus } from "@/api/client";
import { PIPELINE, stepState, type StepState } from "@/lib/plain";
import { cn } from "@/lib/utils";

const DOT: Record<StepState, string> = {
  done: "bg-ok text-white border-ok",
  active: "bg-brand-soft text-brand border-brand",
  waiting: "bg-surface text-ink-subtle border-line-strong",
  failed: "bg-danger text-white border-danger",
};

const STATE_TEXT: Record<StepState, string> = {
  done: "done",
  active: "in progress",
  waiting: "waiting",
  failed: "failed",
};

/** The five processing steps, lighting up as the server reports each one. */
export function Pipeline({
  status,
  processing,
  failedAt,
}: {
  status: WorkflowStatus | null;
  processing: boolean;
  failedAt?: WorkflowStatus | undefined;
}) {
  return (
    <ol className="grid grid-cols-1 gap-3 sm:grid-cols-5" aria-label="Processing steps">
      {PIPELINE.map((step, i) => {
        const state: StepState = status ? stepState(status, i, processing, failedAt) : "waiting";
        return (
          <li
            key={step.status}
            className={cn(
              "flex items-start gap-3 rounded-lg border p-3 transition-colors sm:flex-col sm:items-center sm:text-center",
              state === "active" ? "border-brand/40 bg-brand-soft/40" : "border-line bg-surface",
            )}
          >
            <span
              className={cn("grid size-8 shrink-0 place-items-center rounded-full border-2 text-sm font-semibold", DOT[state])}
              aria-hidden
            >
              {state === "done" ? (
                <Check className="size-4" />
              ) : state === "active" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : state === "failed" ? (
                <X className="size-4" />
              ) : (
                i + 1
              )}
            </span>
            <span>
              <span className="block text-sm font-semibold text-ink">{step.title}</span>
              <span className="block text-xs text-ink-muted">{step.detail}</span>
              <span className="sr-only">: {STATE_TEXT[state]}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
