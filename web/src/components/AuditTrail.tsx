import { Fingerprint, ShieldCheck, ShieldX } from "lucide-react";
import { useEffect, useState } from "react";

import { api, friendlyError, type AuditEvent } from "@/api/client";
import { ErrorState } from "@/components/States";
import { Term } from "@/components/Term";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { auditText, shortHash } from "@/lib/plain";

function time(ts: string | undefined): string {
  return ts ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
}

export function AuditTrail({ documentId, version = 0 }: { documentId: string; version?: number }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [check, setCheck] = useState<{ valid: boolean; checked_events: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, [documentId, version]);

  if (error) return <ErrorState message={error} />;
  if (!events || !check) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="space-y-4">
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${check.valid ? "border-ok/30 bg-ok-soft" : "border-danger/30 bg-danger-soft"}`}
        data-testid="tamper-check"
      >
        {check.valid ? (
          <ShieldCheck className="size-6 text-ok" aria-hidden />
        ) : (
          <ShieldX className="size-6 text-danger" aria-hidden />
        )}
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

      <ol className="relative space-y-0 border-l-2 border-line pl-6" aria-label="Audit trail">
        {events.map((e) => {
          const examples = e.details?.["examples"];
          return (
            <li key={e.event_id} className="relative pb-4">
              <span
                className={`absolute -left-[31px] top-1 size-3 rounded-full border-2 border-surface ${
                  e.event_type.startsWith("guardrail") ? "bg-danger" : e.event_type.startsWith("review") ? "bg-warn" : "bg-brand"
                }`}
                aria-hidden
              />
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-sm font-medium text-ink">{auditText(e)}</span>
                <span className="text-xs text-ink-subtle">{time(e.timestamp)}</span>
              </div>
              {Array.isArray(examples) && examples.length > 0 && (
                <p className="mt-1 rounded bg-danger-soft px-2 py-1 font-mono text-xs text-danger">
                  “{String(examples[0])}”
                </p>
              )}
              <span className="mt-1 inline-flex items-center gap-1 text-xs text-ink-subtle">
                <Fingerprint className="size-3" aria-hidden /> {shortHash(e.event_hash)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-ink-subtle">
        The <Term k="audit">audit trail</Term> is append-only. Records are kept even after your
        documents are deleted. They hold identifiers, fingerprints, decisions and short excerpts
        flagged by safety checks, not the documents themselves.{" "}
        <Badge tone="neutral">{events.length} records</Badge>
      </p>
    </div>
  );
}
