import { Fingerprint, ShieldCheck, ShieldX } from "lucide-react";
import { useEffect, useState } from "react";

import { api, friendlyError, type AuditEvent } from "@/api/client";
import { ErrorState } from "@/components/States";
import { Term } from "@/components/Term";
import { Skeleton } from "@/components/ui/skeleton";
import { auditText, shortHash } from "@/lib/plain";
import { cn } from "@/lib/utils";

function time(ts: string | undefined): string {
  return ts ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
}

function dotTone(type: string): string {
  if (type.startsWith("guardrail")) return "bg-danger shadow-[0_0_0_4px_rgb(255_122_122/0.15)]";
  if (type.startsWith("review")) return "bg-warn shadow-[0_0_0_4px_rgb(245_185_74/0.15)]";
  if (type === "workflow.completed") return "bg-ok shadow-[0_0_0_4px_rgb(61_220_151/0.15)]";
  return "bg-brand/80";
}

export function AuditTrail({ documentId, version = 0 }: { documentId: string; version?: number }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [check, setCheck] = useState<{ valid: boolean; checked_events: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    Promise.all([api.audit(documentId), api.verifyAudit(documentId)])
      .then(([a, v]) => {
        if (!alive) return;
        setEvents(a.events);
        setCheck(v);
      })
      .catch((e: unknown) => alive && setError(friendlyError(e)));
    return () => {
      alive = false;
    };
  }, [documentId, version, attempt]);

  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => {
          setError(null);
          setAttempt((a) => a + 1);
        }}
      />
    );
  }
  if (!events || !check) {
    return (
      <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading the audit trail">
        <Skeleton className="h-20 w-full rounded-xl" />
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div
        className={cn(
          "relative flex items-center gap-4 overflow-hidden rounded-xl border p-4 animate-fade-up",
          check.valid ? "border-ok-line bg-ok-soft" : "border-danger-line bg-danger-soft",
        )}
        data-testid="tamper-check"
      >
        <span
          className={cn(
            "relative grid size-12 shrink-0 place-items-center rounded-full border-2",
            check.valid ? "border-ok/50 text-ok" : "border-danger/60 text-danger",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "absolute inset-1 rounded-full border border-dashed",
              check.valid ? "border-ok/40" : "border-danger/40",
            )}
          />
          {check.valid ? <ShieldCheck className="size-5" aria-hidden /> : <ShieldX className="size-5" aria-hidden />}
        </span>
        <div className="text-sm">
          <p className="font-semibold text-ink">
            <Term k="tamper">Tamper check</Term> {check.valid ? "passed" : "FAILED"}
          </p>
          <p className="text-ink-muted">
            {check.valid
              ? `All ${check.checked_events} records still match their fingerprints, so none has been edited since it was written.`
              : "At least one record no longer matches its fingerprint."}
          </p>
        </div>
      </div>

      <ol className="relative" aria-label="Audit trail">
        <span aria-hidden className="absolute bottom-3 left-[5px] top-3 w-px bg-gradient-to-b from-line-bright via-line-strong to-transparent" />
        {events.map((e, i) => {
          const examples = e.details?.["examples"];
          return (
            <li
              key={e.event_id}
              className="relative animate-fade-in pb-4 pl-7 last:pb-0"
              style={{ animationDelay: `${Math.min(i, 12) * 35}ms` }}
            >
              <span aria-hidden className={cn("absolute left-0 top-1.5 size-[11px] rounded-full border-2 border-canvas", dotTone(e.event_type))} />
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <span className="text-sm text-ink">{auditText(e)}</span>
                <span className="num text-[11px] text-ink-subtle">{time(e.timestamp)}</span>
              </div>
              {Array.isArray(examples) && examples.length > 0 && (
                <p className="mt-1.5 rounded-md border border-danger-line bg-danger-soft px-2 py-1 font-mono text-xs text-danger">
                  “{String(examples[0])}”
                </p>
              )}
              <span className="mt-0.5 inline-flex items-center gap-1 font-mono text-[11px] text-ink-subtle">
                <Fingerprint className="size-3" aria-hidden /> {shortHash(e.event_hash)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="border-t border-line pt-4 text-xs leading-relaxed text-ink-subtle">
        The <Term k="audit">audit trail</Term> is append-only: <span className="num">{events.length}</span> records
        for this document. Records are kept even after your documents are deleted. They hold
        identifiers, fingerprints, decisions and short excerpts flagged by safety checks, not the
        documents themselves.
      </p>
    </div>
  );
}
