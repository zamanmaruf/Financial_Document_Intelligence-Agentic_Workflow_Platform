import { FileText, ShieldAlert } from "lucide-react";

import type { Document } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { documentTypeText, STATUS_TEXT, statusTone } from "@/lib/plain";

export function DocumentSummary({ doc }: { doc: Document }) {
  const injected = doc.security_flags.includes("prompt_injection_suspected");
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface p-4">
      <span className="grid size-10 place-items-center rounded-md bg-surface-muted text-ink-muted">
        <FileText className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-ink">{doc.filename}</p>
        <p className="text-sm text-ink-muted">
          {documentTypeText(doc.document_type)} · {doc.page_count} page{doc.page_count === 1 ? "" : "s"}
        </p>
      </div>
      {injected && (
        <Badge tone="danger">
          <ShieldAlert aria-hidden /> Hidden instructions detected
        </Badge>
      )}
      <Badge tone={statusTone(doc.status)} aria-live="polite">
        {doc.processing && doc.status !== "READY" && doc.status !== "NEEDS_REVIEW"
          ? "Working…"
          : STATUS_TEXT[doc.status]}
      </Badge>
    </div>
  );
}
