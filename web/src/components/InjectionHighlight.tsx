import { LocateFixed, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { injectionHighlightId, injectionHighlights, type Highlight } from "@/components/viewer/highlights";

/** The suspicious passages the scanner flagged, taken from the document's audit record. */
export function InjectionHighlight({
  documentId,
  onLocate,
  onHighlights,
}: {
  documentId: string;
  onLocate?: (id: string) => void;
  onHighlights?: (highlights: Highlight[]) => void;
}) {
  const [examples, setExamples] = useState<string[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .audit(documentId)
      .then((a) => {
        if (!alive) return;
        const event = a.events.find((e) => e.event_type === "guardrail.document_injection_suspected");
        const raw = event?.details?.["examples"];
        const found = Array.isArray(raw) ? raw.map(String) : [];
        setExamples(found);
        onHighlights?.(injectionHighlights(found));
      })
      .catch(() => alive && setExamples([]));
    return () => {
      alive = false;
    };
    // onHighlights is a notification; re-running on its identity would refetch needlessly
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  if (examples === null) return <Skeleton className="h-28 w-full rounded-xl" />;
  if (examples.length === 0) return null;
  return (
    <div
      className="animate-fade-up space-y-3 rounded-xl border border-danger-line bg-danger-soft p-4"
      data-testid="injection"
    >
      <p className="flex items-center gap-2 text-sm font-semibold text-danger">
        <ShieldAlert className="size-4" aria-hidden /> Text in the document aimed at AI systems
      </p>
      <div className="space-y-1.5">
        {examples.map((ex) => (
          <blockquote
            key={ex}
            className="rounded-lg border border-danger-line bg-canvas/60 px-3 py-2 font-mono text-[13px] leading-relaxed text-ink"
          >
            …{ex}…
          </blockquote>
        ))}
      </div>
      <p className="text-sm leading-relaxed text-ink-muted">
        Document text is handled as data, not as instructions. It extracted the real figures, flagged the
        document and sent it to a person instead of approving anything.
      </p>
      {onLocate && (
        <button
          type="button"
          onClick={() => onLocate(injectionHighlightId(0))}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-danger hover:underline"
        >
          <LocateFixed className="size-3.5" aria-hidden /> Show it on the page
        </button>
      )}
    </div>
  );
}
