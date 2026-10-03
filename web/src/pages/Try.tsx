import { FileUp, Inbox, Loader2, RefreshCw, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import { api, friendlyError, type Document, type Review, type Sample } from "@/api/client";
import { AskPanel } from "@/components/AskPanel";
import { AuditTrail } from "@/components/AuditTrail";
import { DocumentSummary } from "@/components/DocumentSummary";
import { FieldsView } from "@/components/FieldsView";
import { InjectionHighlight } from "@/components/InjectionHighlight";
import { Pipeline } from "@/components/Pipeline";
import { ReviewPanel } from "@/components/ReviewPanel";
import { Callout, EmptyState, ErrorState } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { useDocumentRun } from "@/hooks/useDocumentRun";
import { documentTypeText, STATUS_TEXT, statusTone } from "@/lib/plain";
import { cn } from "@/lib/utils";

type Tab = "results" | "ask" | "review" | "audit";

const TABS: { id: Tab; label: string }[] = [
  { id: "results", label: "Results" },
  { id: "ask", label: "Ask questions" },
  { id: "review", label: "Review" },
  { id: "audit", label: "Audit trail" },
];

const GENERIC_QUESTIONS = ["What kind of document is this?", "What is the total amount?"];

function SamplePicker({ onPick, disabled }: { onPick: (s: Sample) => void; disabled: boolean }) {
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.samples().then(setSamples).catch((e: unknown) => setError(friendlyError(e)));
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!samples) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {samples.map((s) => (
        <button
          key={s.sample_id}
          type="button"
          disabled={disabled}
          onClick={() => onPick(s)}
          className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-4 text-left shadow-card transition-colors hover:border-brand disabled:opacity-50"
        >
          <span className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-ink-subtle">{s.document_kind}</span>
            <Badge tone={s.expected_outcome === "READY" ? "ok" : "warn"}>
              {s.expected_outcome === "READY" ? "Should pass" : "Should need a person"}
            </Badge>
          </span>
          <span className="font-medium text-ink">{s.title}</span>
          <span className="text-sm text-ink-muted">{s.summary}</span>
        </button>
      ))}
    </div>
  );
}

function UploadZone({ onFile, disabled }: { onFile: (f: File) => void; disabled: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const { status } = useDemoStatus();

  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file && !disabled) onFile(file);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
        over ? "border-brand bg-brand-soft/50" : "border-line-strong bg-surface",
      )}
    >
      <FileUp className="size-8 text-ink-subtle" aria-hidden />
      <p className="font-medium text-ink">Drop a PDF here</p>
      <p className="text-sm text-ink-muted">
        Up to {status?.limits.max_upload_mb ?? 5} MB and {status?.limits.max_pages ?? 10} pages. Works
        best with invoices, bank statements, income statements, balance sheets and fund factsheets.
      </p>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        id="upload-input"
        aria-label="Upload a PDF"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      <Button variant="secondary" disabled={disabled} onClick={() => input.current?.click()}>
        <Upload aria-hidden /> Choose a file
      </Button>
    </div>
  );
}

function Workspace({
  onOpen,
  refreshKey,
}: {
  onOpen: (doc: Document, tab?: Tab) => void;
  refreshKey: number;
}) {
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [pending, setPending] = useState<Review[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api.documents(), api.reviews()])
      .then(([d, r]) => {
        setDocs(d);
        setPending(r.items.filter((i) => i.status === "pending" && i.target_type === "document_processing"));
      })
      .catch((e: unknown) => setError(friendlyError(e)));
  }, []);

  useEffect(load, [load, refreshKey]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Your documents</CardTitle>
        <Button variant="ghost" size="sm" onClick={load} aria-label="Refresh your documents">
          <RefreshCw aria-hidden />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && <ErrorState message={error} />}
        {!docs && !error && <Skeleton className="h-20" />}
        {docs && docs.length === 0 && (
          <p className="text-sm text-ink-muted">Nothing yet. Pick a sample or upload a PDF.</p>
        )}
        {pending.length > 0 && (
          <p className="flex items-center gap-2 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
            <Inbox className="size-4" aria-hidden /> {pending.length} waiting for your review
          </p>
        )}
        <ul className="divide-y divide-line">
          {docs?.map((d) => {
            const needsYou = pending.some((p) => p.document_id === d.document_id);
            return (
              <li key={d.document_id}>
                <button
                  type="button"
                  onClick={() => onOpen(d, needsYou ? "review" : "results")}
                  className="flex w-full flex-col items-start gap-1 py-2.5 text-left hover:text-brand"
                >
                  <span className="block w-full truncate text-sm font-medium">{d.filename}</span>
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-ink-muted">{documentTypeText(d.document_type)}</span>
                    <Badge tone={statusTone(d.status)}>{STATUS_TEXT[d.status]}</Badge>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

export function Try() {
  const run = useDocumentRun();
  const [tab, setTab] = useState<Tab>("results");
  const [questions, setQuestions] = useState<string[]>(GENERIC_QUESTIONS);
  const [version, setVersion] = useState(0);
  const { status } = useDemoStatus();
  const busy = run.phase === "uploading" || run.phase === "processing";

  const bump = () => setVersion((v) => v + 1);

  async function after(promise: Promise<void>) {
    await promise;
    bump();
  }

  function pickSample(s: Sample) {
    setTab("results");
    setQuestions(s.suggested_questions);
    void after(run.start(() => api.loadSample(s.sample_id)));
  }

  function uploadFile(f: File) {
    setTab("results");
    setQuestions(GENERIC_QUESTIONS);
    void after(run.start(() => api.upload(f)));
  }

  function open(doc: Document, t: Tab = "results") {
    setTab(t);
    setQuestions(GENERIC_QUESTIONS);
    void run.start(() => Promise.resolve({ document: doc }));
  }

  const doc = run.doc;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <div className="mb-8 max-w-2xl space-y-2">
        <h1 className="text-3xl font-semibold text-ink">Try it yourself</h1>
        <p className="text-ink-muted">
          Pick a sample document or upload your own PDF, then explore the results, ask questions and
          act as the reviewer.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          {!doc && run.phase !== "uploading" && (
            <>
              <section aria-labelledby="samples-heading" className="space-y-3">
                <h2 id="samples-heading" className="font-semibold text-ink">
                  Start with a sample
                </h2>
                <SamplePicker onPick={pickSample} disabled={busy} />
              </section>
              <section aria-labelledby="upload-heading" className="space-y-3">
                <h2 id="upload-heading" className="font-semibold text-ink">
                  Or upload your own
                </h2>
                <Callout tone="warn" title="Please don't upload real financial documents">
                  This is a public demo. Your files are visible only to your browser session and are
                  deleted after {status?.limits.retention_hours ?? 24} hours, and documents may be
                  sent to an AI provider (Claude on AWS Bedrock) for processing.
                </Callout>
                <UploadZone onFile={uploadFile} disabled={busy} />
              </section>
              {run.error && <ErrorState message={run.error} />}
            </>
          )}

          {(doc || run.phase === "uploading") && (
            <section className="space-y-5" aria-label="Current document">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-semibold text-ink">Processing</h2>
                <Button variant="secondary" size="sm" onClick={run.reset} disabled={busy}>
                  Choose another document
                </Button>
              </div>
              <Pipeline status={doc?.status ?? null} processing={busy} failedAt={run.lastStep} />
              {doc && <DocumentSummary doc={doc} />}
              {run.error && <ErrorState message={run.error} />}
              {run.phase === "uploading" && (
                <p className="flex items-center gap-2 text-sm text-ink-muted">
                  <Loader2 className="size-4 animate-spin" aria-hidden /> Uploading…
                </p>
              )}

              {doc && run.phase === "done" && doc.status === "FAILED" && (
                <ErrorState message="This document couldn't be processed. It may be empty, image-only without readable text, or damaged." />
              )}

              {doc && run.phase === "done" && doc.status !== "FAILED" && (
                <div className="space-y-4">
                  {doc.security_flags.includes("prompt_injection_suspected") && (
                    <InjectionHighlight documentId={doc.document_id} />
                  )}
                  <div role="tablist" aria-label="Document views" className="flex gap-1 overflow-x-auto border-b border-line">
                    {TABS.map((t) => (
                      <button
                        key={t.id}
                        role="tab"
                        type="button"
                        id={`tab-${t.id}`}
                        aria-selected={tab === t.id}
                        aria-controls={`panel-${t.id}`}
                        onClick={() => setTab(t.id)}
                        className={cn(
                          "-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium",
                          tab === t.id ? "border-brand text-brand" : "border-transparent text-ink-muted hover:text-ink",
                        )}
                      >
                        {t.label}
                        {t.id === "review" && doc.status === "NEEDS_REVIEW" && (
                          <span className="ml-1.5 inline-block size-2 rounded-full bg-warn" aria-label="needs attention" />
                        )}
                      </button>
                    ))}
                  </div>
                  <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
                    {tab === "results" && <FieldsView documentId={doc.document_id} version={version} />}
                    {tab === "ask" &&
                      (doc.status === "READY" || doc.status === "NEEDS_REVIEW" ? (
                        <AskPanel documentId={doc.document_id} suggestions={questions} />
                      ) : (
                        <EmptyState title="Questions aren't available" body="This document was rejected, so it can't be queried." />
                      ))}
                    {tab === "review" && (
                      <ReviewPanel
                        key={`${doc.document_id}-${version}`}
                        documentId={doc.document_id}
                        onResolved={() => {
                          void run.reload();
                          bump();
                        }}
                      />
                    )}
                    {tab === "audit" && <AuditTrail documentId={doc.document_id} version={version} />}
                  </div>
                </div>
              )}
            </section>
          )}
        </div>

        <aside className="space-y-4">
          <Workspace onOpen={open} refreshKey={version} />
          {status?.session_active && (
            <Card>
              <CardContent className="space-y-1 pt-5 text-sm text-ink-muted">
                <p>
                  <span className="font-medium text-ink">{status.documents_remaining}</span> of{" "}
                  {status.limits.documents_per_day} documents left today
                </p>
                <p>
                  <span className="font-medium text-ink">{status.questions_remaining}</span> of{" "}
                  {status.limits.questions_per_day} questions left today
                </p>
              </CardContent>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
