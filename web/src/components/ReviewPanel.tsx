import { CheckCircle2, LocateFixed, UserCheck, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api, friendlyError, type Entity, type Review } from "@/api/client";
import { Callout, ErrorState } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  conflictHighlightId,
  conflictHighlights,
  fieldHighlights,
  type Highlight,
} from "@/components/viewer/highlights";
import { fieldLabel, formatValue, reasonText, VALIDATION_TEXT } from "@/lib/plain";
import { cn } from "@/lib/utils";

interface OriginalOutput {
  extraction?: { entities?: Entity[] } | null;
}

function flaggedFields(review: Review): Entity[] {
  const original = review.original_output as OriginalOutput;
  return (original.extraction?.entities ?? []).filter(
    (e) => e.validation_status !== "valid" && e.validation_status !== "corrected",
  );
}

function candidates(f: Entity): (string | number)[] {
  return [f.value, ...(f.alternatives ?? [])].filter(
    (v, i, all): v is string | number => v !== null && v !== undefined && all.indexOf(v) === i,
  );
}

function reviewHighlights(fields: Entity[]): Highlight[] {
  return fields.flatMap((f) => (candidates(f).length > 1 ? conflictHighlights(f) : fieldHighlights([f])));
}

function parseInput(raw: string, current: Entity["value"]): string | number {
  const trimmed = raw.trim();
  if (typeof current === "number" || /^-?[\d,]+(\.\d+)?%?$/.test(trimmed)) {
    const n = Number(trimmed.replace(/[,%\s]/g, ""));
    if (Number.isFinite(n)) return n;
  }
  return trimmed;
}

export function ReviewPanel({
  documentId,
  onResolved,
  activeId,
  onLocate,
  onHighlights,
}: {
  documentId: string;
  onResolved?: (review: Review) => void;
  activeId?: string | null;
  onLocate?: (id: string) => void;
  onHighlights?: (highlights: Highlight[]) => void;
}) {
  const [review, setReview] = useState<Review | null | undefined>(undefined);
  const [resolved, setResolved] = useState<Review | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"approve" | "reject" | "correct" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .reviews(documentId)
      .then((r) => {
        if (!alive) return;
        const docReviews = r.items.filter((i) => i.target_type === "document_processing");
        const pending = docReviews.find((i) => i.status === "pending") ?? null;
        const flagged = pending ? flaggedFields(pending) : [];
        setReview(pending);
        setResolved(docReviews.find((i) => i.status !== "pending" && i.status !== "superseded") ?? null);
        setValues(
          Object.fromEntries(
            flagged.map((f) => [f.name, f.value === null || f.value === undefined ? "" : formatValue(f.name, f.value)]),
          ),
        );
        onHighlights?.(reviewHighlights(flagged));
      })
      .catch((e: unknown) => alive && setError(friendlyError(e)));
    return () => {
      alive = false;
    };
    // onHighlights is a notification; re-running on its identity would refetch needlessly
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, attempt]);

  const fields = useMemo(() => (review ? flaggedFields(review) : []), [review]);

  const changed = fields.filter((f) => {
    const v = values[f.name]?.trim() ?? "";
    return v !== "" && parseInput(v, f.value) !== f.value;
  });

  async function act(kind: "approve" | "reject" | "correct") {
    if (!review) return;
    setBusy(kind);
    setError(null);
    try {
      const comment = "Checked in the public demo";
      const result =
        kind === "approve"
          ? await api.approve(review.review_id, comment)
          : kind === "reject"
            ? await api.reject(review.review_id, comment)
            : await api.correct(
                review.review_id,
                Object.fromEntries(changed.map((f) => [f.name, parseInput(values[f.name] ?? "", f.value)])),
                comment,
              );
      setReview(null);
      setResolved(result);
      onResolved?.(result);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(null);
    }
  }

  if (review === undefined && !error) {
    return <Skeleton className="h-56 w-full rounded-xl" />;
  }

  if (!review) {
    if (resolved) {
      const verb = { approved: "approved", rejected: "rejected", corrected: "corrected and approved" }[
        resolved.status as "approved" | "rejected" | "corrected"
      ];
      return (
        <Callout
          tone={resolved.status === "rejected" ? "danger" : "ok"}
          icon={resolved.status === "rejected" ? <XCircle /> : <CheckCircle2 />}
          title={`You ${verb ?? resolved.status} this document.`}
          className="animate-fade-up"
        >
          {resolved.corrected_output && "Your corrected values are now the official record, marked as corrected by a person."}{" "}
          The decision, who made it and when are saved in the audit trail.
        </Callout>
      );
    }
    return error ? (
      <ErrorState
        message={error}
        onRetry={() => {
          setError(null);
          setAttempt((a) => a + 1);
        }}
      />
    ) : (
      <Callout tone="ok" icon={<CheckCircle2 />} title="Nothing to review">
        Every check passed, so this document didn&apos;t need a person.
      </Callout>
    );
  }

  return (
    <div className="space-y-5 rounded-xl border border-warn-line bg-surface p-4 sm:p-5" data-testid="review-panel">
      <div className="space-y-3">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-warn-soft text-warn">
            <UserCheck className="size-4" aria-hidden />
          </span>
          <h3 className="font-semibold text-ink">Why a person is needed</h3>
        </div>
        <ul className="space-y-1.5">
          {review.reasons.map((r) => (
            <li key={r} className="flex gap-2.5 text-sm text-ink">
              <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warn" aria-hidden />
              {reasonText(r)}
            </li>
          ))}
        </ul>
        {review.details.length > 0 && (
          <details className="group text-xs text-ink-muted">
            <summary className="cursor-pointer select-none hover:text-ink">Technical details</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 font-mono">
              {review.details.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {fields.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-ink">
            Check these values against the document{onLocate ? ". Click a value to see where it appears." : ":"}
          </p>
          {fields.map((f) => {
            const options = candidates(f);
            return (
              <div key={f.name} className="space-y-2.5 rounded-lg border border-line bg-white/[0.02] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label htmlFor={`fix-${f.name}`} className="text-sm font-medium text-ink">
                    {fieldLabel(f.name)}
                  </label>
                  <Badge tone="warn">{VALIDATION_TEXT[f.validation_status]}</Badge>
                </div>
                {options.length > 1 && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
                    <span className="mr-1">Values in the document:</span>
                    {options.map((v, i) => {
                      const id = conflictHighlightId(f.name, i);
                      const chosen = parseInput(values[f.name] ?? "", f.value) === v;
                      return (
                        <button
                          key={String(v)}
                          type="button"
                          aria-pressed={chosen}
                          onClick={() => {
                            setValues((s) => ({ ...s, [f.name]: formatValue(f.name, v) }));
                            onLocate?.(id);
                          }}
                          className={cn(
                            "num inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium transition-colors",
                            chosen
                              ? "border-warn bg-warn-soft text-ink"
                              : "border-line-strong text-ink hover:border-warn-line hover:bg-warn-soft",
                            activeId === id && "ring-2 ring-warn/40",
                          )}
                        >
                          {onLocate && <LocateFixed className="size-3 opacity-70" aria-hidden />}
                          Use {formatValue(f.name, v)}
                        </button>
                      );
                    })}
                  </div>
                )}
                <input
                  id={`fix-${f.name}`}
                  value={values[f.name] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                  placeholder={f.value === null || f.value === undefined ? "Not in the document: type the correct value" : ""}
                  className="num h-10 w-full rounded-lg border border-line-strong bg-canvas px-3 text-sm text-ink placeholder:text-ink-subtle focus-visible:border-brand-line focus-visible:outline-none"
                />
              </div>
            );
          })}
        </div>
      )}

      {error && <ErrorState message={error} />}

      <div className="flex flex-wrap gap-2 border-t border-line pt-4">
        {changed.length > 0 ? (
          <Button variant="success" onClick={() => void act("correct")} disabled={busy !== null} loading={busy === "correct"}>
            {busy !== "correct" && <CheckCircle2 aria-hidden />}
            Save correction and approve
          </Button>
        ) : (
          <Button variant="success" onClick={() => void act("approve")} disabled={busy !== null} loading={busy === "approve"}>
            {busy !== "approve" && <CheckCircle2 aria-hidden />}
            Approve as is
          </Button>
        )}
        <Button variant="secondary" onClick={() => void act("reject")} disabled={busy !== null} loading={busy === "reject"}>
          {busy !== "reject" && <XCircle aria-hidden />}
          Reject
        </Button>
      </div>
    </div>
  );
}
