import { ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";

/** The suspicious passages the scanner flagged, taken from the document's audit record. */
export function InjectionHighlight({ documentId }: { documentId: string }) {
  const [examples, setExamples] = useState<string[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .audit(documentId)
      .then((a) => {
        if (!alive) return;
        const event = a.events.find((e) => e.event_type === "guardrail.document_injection_suspected");
        const raw = event?.details?.["examples"];
        setExamples(Array.isArray(raw) ? raw.map(String) : []);
      })
      .catch(() => alive && setExamples([]));
    return () => {
      alive = false;
    };
  }, [documentId]);

  if (examples === null) return <Skeleton className="h-24 w-full" />;
  if (examples.length === 0) return null;
  return (
    <div className="space-y-2 rounded-lg border border-danger/30 bg-danger-soft p-4" data-testid="injection">
      <p className="flex items-center gap-2 text-sm font-semibold text-danger">
        <ShieldAlert className="size-4" aria-hidden /> Text in the document aimed at AI systems
      </p>
      {examples.map((ex) => (
        <blockquote key={ex} className="rounded-md bg-surface px-3 py-2 font-mono text-sm text-ink">
          …{ex}…
        </blockquote>
      ))}
      <p className="text-sm text-ink-muted">
        The system never follows instructions found inside documents. It extracted the real
        figures, flagged the document and sent it to a person.
      </p>
    </div>
  );
}
