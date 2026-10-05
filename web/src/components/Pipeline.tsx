import { Check, X } from "lucide-react";

import type { WorkflowStatus } from "@/api/client";
import { PIPELINE, stepState, type StepState } from "@/lib/plain";
import { cn } from "@/lib/utils";

const STATE_TEXT: Record<StepState, string> = {
  done: "done",
  active: "in progress",
  waiting: "waiting",
  failed: "failed",
};

export function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.max(ms, 1).toFixed(0)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function Dot({ state, index }: { state: StepState; index: number }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative z-10 grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold transition-all duration-300",
        state === "done" && "border-ok/60 bg-[#0f1f19] text-ok",
        state === "active" && "border-brand bg-[#17142b] text-brand shadow-[0_0_0_4px_rgb(161_148_255/0.15)]",
        state === "waiting" && "border-line-bright bg-surface text-ink-subtle",
        state === "failed" && "border-danger bg-[#2a1416] text-danger",
      )}
    >
      {state === "done" ? (
        <Check className="size-3.5" strokeWidth={3} />
      ) : state === "failed" ? (
        <X className="size-3.5" strokeWidth={3} />
      ) : state === "active" ? (
        <span className="size-2 animate-pulse-soft rounded-full bg-brand" />
      ) : (
        <span className="num">{index + 1}</span>
      )}
    </span>
  );
}

/**
 * The five processing steps, lighting up as the server reports each one. Lays out as a vertical
 * list in narrow containers and a horizontal track in wide ones.
 */
export function Pipeline({
  status,
  processing,
  failedAt,
  timings,
}: {
  status: WorkflowStatus | null;
  processing: boolean;
  failedAt?: WorkflowStatus | undefined;
  /** Server-measured duration of each finished step, in milliseconds. */
  timings?: Partial<Record<WorkflowStatus, number>>;
}) {
  return (
    <div className="@container">
      <ol className="grid grid-cols-1 @2xl:grid-cols-5" aria-label="Processing steps">
        {PIPELINE.map((step, i) => {
          const state: StepState = status ? stepState(status, i, processing, failedAt) : "waiting";
          const ms = timings?.[step.status];
          const last = i === PIPELINE.length - 1;
          return (
            <li key={step.status} className="relative flex gap-3 pb-4 last:pb-0 @2xl:flex-col @2xl:gap-2.5 @2xl:pb-0">
              {!last && (
                <>
                  <span aria-hidden className="absolute bottom-0 left-[13.5px] top-7 w-px bg-line-strong @2xl:hidden">
                    <span
                      className={cn(
                        "absolute inset-x-0 top-0 bg-ok/60 transition-[height] duration-500 ease-out",
                        state === "done" ? "h-full" : "h-0",
                      )}
                    />
                  </span>
                  <span aria-hidden className="absolute left-9 right-2 top-[13.5px] hidden h-px bg-line-strong @2xl:block">
                    <span
                      className={cn(
                        "absolute inset-y-0 left-0 bg-ok/60 transition-[width] duration-500 ease-out",
                        state === "done" ? "w-full" : "w-0",
                      )}
                    />
                  </span>
                </>
              )}
              <Dot state={state} index={i} />
              <div className="min-w-0 flex-1 @2xl:pr-3">
                <p className="flex items-baseline justify-between gap-2 text-[13px] font-medium text-ink @2xl:justify-start">
                  {step.title}
                  {ms !== undefined && state === "done" && (
                    <span className="num animate-fade-in text-[11px] font-normal text-ink-subtle">{formatMs(ms)}</span>
                  )}
                </p>
                <p className="text-xs leading-snug text-ink-muted">{step.detail}</p>
                <span className="sr-only">: {STATE_TEXT[state]}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
