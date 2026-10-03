import { CheckCircle2, Loader2, UserCheck, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api, friendlyError, type Entity, type Review } from "@/api/client";
import { Callout, ErrorState } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fieldLabel, formatValue, reasonText, VALIDATION_TEXT } from "@/lib/plain";

interface OriginalOutput {
  extraction?: { entities?: Entity[] } | null;
}

function flaggedFields(review: Review): Entity[] {
  const original = review.original_output as OriginalOutput;
  return (original.extraction?.entities ?? []).filter(
    (e) => e.validation_status !== "valid" && e.validation_status !== "corrected",
  );
}

function parseInput(raw: string, current: Entity["value"]): string | number {
  const trimmed = raw.trim();
  if (typeof current === "number" || /^-?[\d,]+(\.\d+)?$/.test(trimmed)) {
    const n = Number(trimmed.replace(/,/g, ""));
    if (Number.isFinite(n)) return n;
  }
  return trimmed;
}

export function ReviewPanel({
  documentId,
  onResolved,
}: {
  documentId: string;
  onResolved?: (review: Review) => void;
}) {
  const [review, setReview] = useState<Review | null | undefined>(undefined);
  const [resolved, setResolved] = useState<Review | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"approve" | "reject" | "correct" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .reviews(documentId)
      .then((r) => {
        if (!alive) return;
        const docReviews = r.items.filter((i) => i.target_type === "document_processing");
        const pending = docReviews.find((i) => i.status === "pending") ?? null;
        setReview(pending);
        setResolved(docReviews.find((i) => i.status !== "pending" && i.status !== "superseded") ?? null);
        setValues(
          Object.fromEntries(
            (pending ? flaggedFields(pending) : []).map((f) => [
              f.name,
              f.value === null || f.value === undefined ? "" : String(f.value),
            ]),
          ),
        );
      })
      .catch((e: unknown) => alive && setError(friendlyError(e)));
    return () => {
      alive = false;
    };
  }, [documentId]);

  const fields = useMemo(() => (review ? flaggedFields(review) : []), [review]);

  const changed = fields.filter((f) => {
    const v = values[f.name]?.trim() ?? "";
    return v !== "" && v !== String(f.value ?? "");
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
    return <Skeleton className="h-48 w-full" />;
  }

  if (!review) {
    if (resolved) {
      const verb = { approved: "approved", rejected: "rejected", corrected: "corrected and approved" }[
        resolved.status as "approved" | "rejected" | "corrected"
      ];
      return (
        <Callout
          tone={resolved.status === "rejected" ? "danger" : "ok"}
          icon={resolved.status === "rejected" ? <XCircle className="text-danger" /> : <CheckCircle2 className="text-ok" />}
          title={`You ${verb ?? resolved.status} this document.`}
        >
          {resolved.corrected_output && "Your corrected values are now the official record, marked as corrected by a person."}{" "}
          The decision, who made it and when are saved in the audit trail.
        </Callout>
      );
    }
    return error ? (
      <ErrorState message={error} />
    ) : (
      <Callout tone="ok" icon={<CheckCircle2 className="text-ok" />} title="Nothing to review">
        Every check passed, so this document didn't need a person.
      </Callout>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-warn/40 bg-surface p-4" data-testid="review-panel">
      <div className="flex items-center gap-2">
        <UserCheck className="size-5 text-warn" aria-hidden />
        <h3 className="font-semibold text-ink">Why a person is needed</h3>
      </div>
      <ul className="space-y-2">
        {review.reasons.map((r) => (
          <li key={r} className="flex gap-2 text-sm text-ink">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warn" aria-hidden />
            {reasonText(r)}
          </li>
        ))}
      </ul>
      {review.details.length > 0 && (
        <details className="text-xs text-ink-muted">
          <summary className="cursor-pointer">Technical details</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 font-mono">
            {review.details.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </details>
      )}

      {fields.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-ink">Check these values against the document:</p>
          {fields.map((f) => (
            <div key={f.name} className="space-y-2 rounded-md border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label htmlFor={`fix-${f.name}`} className="text-sm font-medium text-ink">
                  {fieldLabel(f.name)}
                </label>
                <Badge tone="warn">{VALIDATION_TEXT[f.validation_status]}</Badge>
              </div>
              <input
                id={`fix-${f.name}`}
                value={values[f.name] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                placeholder={f.value === null || f.value === undefined ? "Not in the document: type the correct value" : ""}
                className="h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink"
              />
              {[f.value, ...(f.alternatives ?? [])].filter((v) => v !== null && v !== undefined).length > 1 && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                  Values in the document:
                  {[f.value, ...(f.alternatives ?? [])]
                    .filter((v): v is string | number => v !== null && v !== undefined)
                    .map((v) => (
                      <button
                        key={String(v)}
                        type="button"
                        onClick={() => setValues((s) => ({ ...s, [f.name]: String(v) }))}
                        className="rounded-full border border-line-strong px-2.5 py-1 text-ink hover:border-brand hover:text-brand"
                      >
                        Use {formatValue(f.name, v)}
                      </button>
                    ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {error && <ErrorState message={error} />}

      <div className="flex flex-wrap gap-2">
        {changed.length > 0 ? (
          <Button variant="success" onClick={() => void act("correct")} disabled={busy !== null}>
            {busy === "correct" ? <Loader2 className="animate-spin" aria-hidden /> : <CheckCircle2 aria-hidden />}
            Save correction and approve
          </Button>
        ) : (
          <Button variant="success" onClick={() => void act("approve")} disabled={busy !== null}>
            {busy === "approve" ? <Loader2 className="animate-spin" aria-hidden /> : <CheckCircle2 aria-hidden />}
            Approve as is
          </Button>
        )}
        <Button variant="secondary" onClick={() => void act("reject")} disabled={busy !== null}>
          {busy === "reject" ? <Loader2 className="animate-spin" aria-hidden /> : <XCircle aria-hidden />}
          Reject
        </Button>
      </div>
    </div>
  );
}
