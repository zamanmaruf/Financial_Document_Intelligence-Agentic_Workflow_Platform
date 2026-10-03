import { ChevronDown, Quote } from "lucide-react";
import { useEffect, useState } from "react";

import { api, friendlyError, type Entity, type Extraction } from "@/api/client";
import { ErrorState, EmptyState } from "@/components/States";
import { Term } from "@/components/Term";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
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

function FieldRow({ entity }: { entity: Entity }) {
  const [open, setOpen] = useState(false);
  const missing = entity.value === null || entity.value === undefined;
  const hasEvidence = Boolean(entity.evidence?.snippet);
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        className="grid w-full grid-cols-1 gap-2 px-4 py-3 text-left hover:bg-surface-muted/60 sm:grid-cols-[1.2fr_1.4fr_auto] sm:items-center"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        disabled={!hasEvidence && !entity.alternatives?.length}
      >
        <span className="text-sm text-ink-muted">{fieldLabel(entity.name)}</span>
        <span className={cn("font-medium", missing ? "text-ink-subtle italic" : "text-ink")}>
          {formatValue(entity.name, entity.value)}
        </span>
        <span className="flex flex-wrap items-center gap-2 sm:justify-end">
          {!missing && (
            <Badge tone={SURE_TONE[sureness(entity.confidence)]}>{confidenceWords(entity.confidence)}</Badge>
          )}
          <Badge tone={validationTone(entity.validation_status)}>
            {VALIDATION_TEXT[entity.validation_status]}
          </Badge>
          {(hasEvidence || Boolean(entity.alternatives?.length)) && (
            <ChevronDown
              className={cn("size-4 text-ink-subtle transition-transform", open && "rotate-180")}
              aria-hidden
            />
          )}
        </span>
      </button>
      {open && (
        <div className="space-y-2 px-4 pb-4">
          {hasEvidence && (
            <figure className="rounded-md border-l-4 border-brand bg-brand-soft/50 px-3 py-2">
              <figcaption className="mb-1 flex items-center gap-1.5 text-xs font-medium text-brand">
                <Quote className="size-3.5" aria-hidden />
                Found here{entity.evidence?.page_number ? ` (page ${entity.evidence.page_number})` : ""}
                {entity.evidence?.verified ? " · confirmed in the document" : " · not confirmed"}
              </figcaption>
              <blockquote className="font-mono text-sm text-ink">{entity.evidence?.snippet}</blockquote>
            </figure>
          )}
          {Boolean(entity.alternatives?.length) && (
            <p className="text-sm text-warn">
              The document also shows:{" "}
              <span className="font-medium">
                {entity.alternatives?.map((a) => formatValue(entity.name, a)).join(", ")}
              </span>
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function FieldsView({ documentId, version = 0 }: { documentId: string; version?: number }) {
  const [extraction, setExtraction] = useState<Extraction | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .extractions(documentId)
      .then((r) => {
        if (!alive) return;
        setError(null);
        setExtraction(r.latest ?? null);
      })
      .catch((e: unknown) => alive && setError(friendlyError(e)));
    return () => {
      alive = false;
    };
  }, [documentId, version]);

  if (error) return <ErrorState message={error} />;
  if (extraction === undefined) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Loading extracted fields">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
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
        Document type: <span className="font-medium text-ink">{documentTypeText(extraction.document_type)}</span>.
        Click any row to see the <Term k="evidence" /> it was taken from.
        {extraction.is_mock && " Produced by the offline engine."}
      </p>
      <ul className="overflow-hidden rounded-lg border border-line bg-surface" aria-label="Extracted fields">
        {extraction.entities.map((e) => (
          <FieldRow key={e.name} entity={e} />
        ))}
      </ul>
    </div>
  );
}
