import { ChevronDown, LocateFixed, Quote } from "lucide-react";
import { useEffect, useState } from "react";

import { api, friendlyError, type Entity, type Extraction } from "@/api/client";
import { ErrorState, EmptyState } from "@/components/States";
import { Term } from "@/components/Term";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fieldHighlights, fieldLocateId, type Highlight } from "@/components/viewer/highlights";
import {
  confidenceWords,
  documentTypeText,
  fieldLabel,
  formatValue,
  sureness,
  VALIDATION_TEXT,
  validationTone,
} from "@/lib/plain";
import { cn } from "@/lib/utils";

const SURE_TONE = { very: "ok", fairly: "ok", somewhat: "warn", not: "warn" } as const;

function FieldRow({
  entity,
  active,
  onLocate,
}: {
  entity: Entity;
  active: boolean;
  onLocate?: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [wasActive, setWasActive] = useState(active);
  if (active !== wasActive) {
    setWasActive(active);
    if (active) setOpen(true); // selected from the page: reveal the quote too
  }
  const missing = entity.value === null || entity.value === undefined;
  const hasEvidence = Boolean(entity.evidence?.snippet);
  const expandable = hasEvidence || Boolean(entity.alternatives?.length);
  const expanded = open;
  return (
    <li
      className={cn(
        "relative border-b border-line transition-colors last:border-b-0",
        active && "bg-white/[0.025]",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-brand to-brand-2 transition-opacity",
          active ? "opacity-100" : "opacity-0",
        )}
      />
      <button
        type="button"
        className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 px-4 py-3 text-left transition-colors hover:bg-white/[0.03] disabled:hover:bg-transparent"
        onClick={() => {
          setOpen(!expanded);
          const target = fieldLocateId(entity);
          if (target && !expanded) onLocate?.(target);
        }}
        aria-expanded={expandable ? expanded : undefined}
        disabled={!expandable}
      >
        <span className="min-w-0">
          <span className="block text-xs text-ink-muted">{fieldLabel(entity.name)}</span>
          <span
            className={cn(
              "num mt-0.5 block break-words text-[15px] font-medium",
              missing ? "italic text-ink-subtle" : "text-ink",
            )}
          >
            {formatValue(entity.name, entity.value)}
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="flex flex-col items-end gap-1 @md:flex-row @md:items-center">
            {!missing && (
              <Badge tone={SURE_TONE[sureness(entity.confidence)]}>{confidenceWords(entity.confidence)}</Badge>
            )}
            <Badge tone={validationTone(entity.validation_status)}>
              {VALIDATION_TEXT[entity.validation_status]}
            </Badge>
          </span>
          {expandable ? (
            <ChevronDown
              className={cn("size-4 shrink-0 text-ink-subtle transition-transform duration-200", expanded && "rotate-180")}
              aria-hidden
            />
          ) : (
            <span className="size-4 shrink-0" aria-hidden />
          )}
        </span>
      </button>
      {expanded && expandable && (
        <div className="animate-fade-in space-y-2 px-4 pb-4">
          {hasEvidence && (
            <figure className="rounded-lg border border-brand-line bg-brand-soft px-3 py-2.5">
              <figcaption className="mb-1 flex flex-wrap items-center gap-x-1.5 text-xs font-medium text-brand">
                <Quote className="size-3.5" aria-hidden />
                Found here{entity.evidence?.page_number ? ` (page ${entity.evidence.page_number})` : ""}
                <span className="text-ink-subtle">
                  {entity.evidence?.verified ? "· confirmed in the document" : "· not confirmed"}
                </span>
              </figcaption>
              <blockquote className="font-mono text-[13px] leading-relaxed text-ink">{entity.evidence?.snippet}</blockquote>
              {onLocate && (
                <button
                  type="button"
                  onClick={() => {
                    const target = fieldLocateId(entity);
                    if (target) onLocate(target);
                  }}
                  className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                >
                  <LocateFixed className="size-3.5" aria-hidden /> Show on the page
                </button>
              )}
            </figure>
          )}
          {Boolean(entity.alternatives?.length) && (
            <p className="text-sm text-warn">
              The document also shows:{" "}
              <span className="num font-medium">
                {entity.alternatives?.map((a) => formatValue(entity.name, a)).join(", ")}
              </span>
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function FieldsView({
  documentId,
  version = 0,
  activeId,
  onLocate,
  onHighlights,
}: {
  documentId: string;
  version?: number;
  activeId?: string | null;
  onLocate?: (id: string) => void;
  onHighlights?: (highlights: Highlight[]) => void;
}) {
  const [extraction, setExtraction] = useState<Extraction | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .extractions(documentId)
      .then((r) => {
        if (!alive) return;
        setError(null);
        setExtraction(r.latest ?? null);
        onHighlights?.(fieldHighlights(r.latest?.entities ?? []));
      })
      .catch((e: unknown) => alive && setError(friendlyError(e)));
    return () => {
      alive = false;
    };
    // onHighlights is a notification; re-running on its identity would refetch needlessly
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  if (extraction === undefined) {
    return (
      <div className="space-y-2" role="status" aria-busy="true" aria-label="Loading extracted fields">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (extraction === null) {
    return (
      <EmptyState
        title="No fields were extracted"
        body="The document type wasn't recognised, so there was no list of fields to fill in. That's the safe outcome: it didn't guess."
      />
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-muted">
        <span className="font-medium text-ink">{documentTypeText(extraction.document_type)}</span>
        <span className="text-ink-subtle"> · </span>
        Click a row to see the <Term k="evidence" /> {onLocate ? "boxed on the page" : "it was taken from"}.
        {extraction.is_mock && " Produced by the offline engine."}
      </p>
      <ul className="@container overflow-hidden rounded-xl border border-line bg-surface" aria-label="Extracted fields">
        {extraction.entities.map((e) => (
          <FieldRow
            key={e.name}
            entity={e}
            active={
              !!activeId &&
              (activeId === fieldLocateId(e) || activeId.startsWith(`conflict:${e.name}:`))
            }
            onLocate={onLocate}
          />
        ))}
      </ul>
    </div>
  );
}
