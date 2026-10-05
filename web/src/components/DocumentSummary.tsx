import { FileText, ShieldAlert } from "lucide-react";

import type { Document } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { documentTypeText, STATUS_TEXT, statusTone } from "@/lib/plain";

export function DocumentSummary({ doc }: { doc: Document }) {
  const injected = doc.security_flags.includes("prompt_injection_suspected");
  const working = doc.processing && doc.status !== "READY" && doc.status !== "NEEDS_REVIEW";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-3.5">
      <span className="grid size-10 shrink-0 place-items-center rounded-lg border border-line-strong bg-surface-raised text-ink-muted">
        <FileText className="size-[18px]" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[13px] text-ink">{doc.filename}</p>
        <p className="text-xs text-ink-muted">
          {documentTypeText(doc.document_type)} · <span className="num">{doc.page_count}</span> page
          {doc.page_count === 1 ? "" : "s"}
        </p>
      </div>
      {injected && (
        <Badge tone="danger">
          <ShieldAlert aria-hidden /> Hidden instructions detected
        </Badge>
      )}
      <Badge tone={working ? "brand" : statusTone(doc.status)} dot={working ? "pulse" : true} aria-live="polite">
        {working ? "Working…" : STATUS_TEXT[doc.status]}
      </Badge>
    </div>
  );
}
