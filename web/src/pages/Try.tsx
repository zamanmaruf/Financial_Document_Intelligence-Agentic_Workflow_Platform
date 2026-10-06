import {
  Ban,
  ChevronDown,
  ClipboardCheck,
  FileText,
  FileUp,
  History,
  Landmark,
  Lightbulb,
  ListChecks,
  MessageSquareText,
  Plus,
  Receipt,
  RefreshCw,
  TrendingUp,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { api, friendlyError, type Document, type Review, type Sample } from "@/api/client";
import { AskPanel } from "@/components/AskPanel";
import { AuditTrail } from "@/components/AuditTrail";
import { DocumentSummary } from "@/components/DocumentSummary";
import { FieldsView } from "@/components/FieldsView";
import { InjectionHighlight } from "@/components/InjectionHighlight";
import { formatMs, Pipeline } from "@/components/Pipeline";
import { ReviewPanel } from "@/components/ReviewPanel";
import { Callout, EmptyState, ErrorState } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
import { Meter } from "@/components/ui/progress";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { DocumentViewer, type Highlight } from "@/components/viewer";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { useDocumentRun, type RunFailure } from "@/hooks/useDocumentRun";
import { useStepTimings } from "@/hooks/useStepTimings";
import { documentTypeText, STATUS_TEXT, statusTone, type Tone } from "@/lib/plain";
import { cn } from "@/lib/utils";

type Tab = "results" | "ask" | "review" | "audit";
type Pane = "details" | "page";

const GENERIC_QUESTIONS = ["What kind of document is this?", "What is the total amount?"];
const WIDE = "(min-width: 1280px)";
const LG = "(min-width: 1024px)";

const KIND_ICON: Record<string, ReactNode> = {
  Invoice: <Receipt aria-hidden />,
  "Income statement": <TrendingUp aria-hidden />,
  "Balance sheet": <Landmark aria-hidden />,
  "Not supported": <Ban aria-hidden />,
};

const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
  neutral: "bg-ink-subtle",
};

/** Which highlight source the viewer shows for each inspector tab. */
const TAB_SOURCE: Record<Tab, string> = { results: "fields", ask: "citations", review: "review", audit: "fields" };

function SampleGallery({ onPick, disabled }: { onPick: (s: Sample) => void; disabled: boolean }) {
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .samples()
      .then((s) => alive && setSamples(s))
      .catch((e: unknown) => alive && setError(friendlyError(e)));
    return () => {
      alive = false;
    };
  }, [attempt]);

  if (error) {
    return (
      <ErrorState
        message={error}
        action={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setError(null);
              setAttempt((a) => a + 1);
            }}
          >
            Try again
          </Button>
        }
      />
    );
  }
  if (!samples) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3" role="status" aria-busy="true" aria-label="Loading samples">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-[184px] rounded-xl" />
        ))}
      </div>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
      {samples.map((s, i) => {
        const ready = s.expected_outcome === "READY";
        return (
          <button
            key={s.sample_id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(s)}
            style={{ animationDelay: `${i * 40}ms` }}
            className="group flex animate-fade-up flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-left shadow-card transition-[border-color,transform,background-color] duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:bg-surface-raised disabled:pointer-events-none disabled:opacity-50"
          >
            <span className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2 text-xs font-medium text-ink-muted">
                <span className="grid size-7 place-items-center rounded-lg border border-line-strong bg-surface-raised text-ink-muted transition-colors group-hover:text-ink [&_svg]:size-3.5">
                  {KIND_ICON[s.document_kind] ?? <FileText aria-hidden />}
                </span>
                {s.document_kind}
              </span>
              <Badge tone={ready ? "ok" : "warn"} dot>
                {ready ? "Should pass" : "Should need a person"}
              </Badge>
            </span>
            <span className="space-y-1">
              <span className="block font-medium text-ink">{s.title}</span>
              <span className="line-clamp-2 block text-sm leading-relaxed text-ink-muted">{s.summary}</span>
            </span>
            <span className="mt-auto flex gap-2 border-t border-line pt-3 text-xs leading-relaxed text-ink-subtle">
              <Lightbulb className="mt-px size-3.5 shrink-0 text-brand" aria-hidden />
              {s.lesson}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function UploadZone({ onFile, disabled }: { onFile: (f: File) => void; disabled: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const { status } = useDemoStatus();
  const limits = status?.limits;

  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file && !disabled) onFile(file);
  }

  const rules = [
    "PDF only",
    `Up to ${limits?.max_upload_mb ?? 5} MB`,
    `Up to ${limits?.max_pages ?? 10} pages`,
    `Deleted after ${limits?.retention_hours ?? 24} hours`,
  ];

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cn(
        "relative flex flex-col items-center gap-4 overflow-hidden rounded-2xl border border-dashed px-6 py-10 text-center transition-colors duration-200",
        over ? "border-brand bg-brand-soft" : "border-line-strong bg-surface/60",
      )}
    >
      <span
        className={cn(
          "grid size-12 place-items-center rounded-2xl border bg-surface-raised shadow-card transition-colors",
          over ? "border-brand-line text-brand" : "border-line-strong text-ink-muted",
        )}
      >
        <FileUp className="size-5" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="font-medium text-ink">{over ? "Drop it to start" : "Drag a PDF here"}</p>
        <p className="text-sm text-ink-muted">
          Works best with invoices, bank statements, income statements, balance sheets and fund factsheets.
        </p>
      </div>
      <ul className="flex flex-wrap justify-center gap-1.5" aria-label="Upload rules">
        {rules.map((r) => (
          <li key={r} className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-muted">
            {r}
          </li>
        ))}
      </ul>
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

function Allowance() {
  const { status } = useDemoStatus();
  if (!status?.session_active || status.documents_remaining === null || status.questions_remaining === null) {
    return (
      <p className="text-xs leading-relaxed text-ink-subtle">
        Each visitor gets {status?.limits.documents_per_day ?? 6} documents and {status?.limits.questions_per_day ?? 25}{" "}
        questions a day.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <Meter value={status.documents_remaining} max={status.limits.documents_per_day} label="Documents left today" />
      <Meter value={status.questions_remaining} max={status.limits.questions_per_day} label="Questions left today" />
    </div>
  );
}

function DocumentList({
  selected,
  onOpen,
  onNew,
  refreshKey,
  busy,
}: {
  selected: string | null;
  onOpen: (doc: Document, tab?: Tab) => void;
  onNew: () => void;
  refreshKey: number;
  busy: boolean;
}) {
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [pending, setPending] = useState<Review[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api.documents(), api.reviews()])
      .then(([d, r]) => {
        setError(null);
        setDocs(d);
        setPending(r.items.filter((i) => i.status === "pending" && i.target_type === "document_processing"));
      })
      .catch((e: unknown) => setError(friendlyError(e)));
  }, []);

  useEffect(load, [load, refreshKey]);

  return (
    <nav aria-label="Your documents" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold text-ink">Your documents</h2>
        <Button variant="ghost" size="icon" onClick={load} aria-label="Refresh your documents" className="size-7">
          <RefreshCw aria-hidden />
        </Button>
      </div>
      <Button variant="secondary" size="sm" className="w-full justify-start" onClick={onNew} disabled={busy}>
        <Plus aria-hidden /> New document
      </Button>
      {pending.length > 0 && (
        <p className="flex items-center gap-2 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-xs text-warn">
          <span className="size-1.5 rounded-full bg-warn" aria-hidden />
          {pending.length} waiting for your review
        </p>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
      {!docs && !error && (
        <div className="space-y-2" role="status" aria-busy="true" aria-label="Loading your documents">
          <Skeleton className="h-11 rounded-lg" />
          <Skeleton className="h-11 rounded-lg" />
        </div>
      )}
      {docs && docs.length === 0 && (
        <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-xs leading-relaxed text-ink-subtle">
          Nothing here yet. Documents you open appear in this list.
        </p>
      )}
      {docs && docs.length > 0 && (
        <ul className="-mx-1 space-y-0.5">
          {docs.map((d) => {
            const needsYou = pending.some((p) => p.document_id === d.document_id);
            const active = d.document_id === selected;
            return (
              <li key={d.document_id}>
                <button
                  type="button"
                  onClick={() => onOpen(d, needsYou ? "review" : "results")}
                  aria-current={active ? "true" : undefined}
                  disabled={busy}
                  className={cn(
                    "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors disabled:opacity-60",
                    active ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
                  )}
                >
                  <span
                    className={cn(
                      "mt-1.5 size-1.5 shrink-0 rounded-full",
                      DOT[statusTone(d.status)],
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate font-mono text-xs", active ? "text-ink" : "text-ink-muted")}>
                      {d.filename}
                    </span>
                    <span className="block text-[11px] text-ink-subtle">
                      {documentTypeText(d.document_type)} · {needsYou ? "Needs you" : STATUS_TEXT[d.status]}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}

function ViewerPlaceholder({ busy }: { busy: boolean }) {
  return (
    <div className="flex aspect-[1/1.2] max-h-[70vh] w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-line-strong bg-surface/50 p-8 text-center">
      <span className="grid size-11 place-items-center rounded-xl border border-line-strong bg-surface-raised text-ink-muted">
        <FileText className="size-5" aria-hidden />
      </span>
      <p className="text-sm font-medium text-ink">{busy ? "Uploading…" : "The page appears here"}</p>
    </div>
  );
}

export function Try() {
  const run = useDocumentRun();
  const [tab, setTab] = useState<Tab>("results");
  const [pane, setPane] = useState<Pane>("details");
  const [questions, setQuestions] = useState<string[]>(GENERIC_QUESTIONS);
  const [version, setVersion] = useState(0);
  const [highlights, setHighlights] = useState<Record<string, Highlight[]>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const { status } = useDemoStatus();
  const { toast } = useToast();
  const navigate = useNavigate();
  const stageRef = useRef<HTMLDivElement>(null);
  const [retry, setRetry] = useState<(() => void) | null>(null);
  const busy = run.phase === "uploading" || run.phase === "processing";
  const doc = run.doc;
  const timings = useStepTimings(doc?.document_id, run.phase === "done");

  // A different document: drop the previous one's boxes (state derived during render).
  const docId = doc?.document_id ?? null;
  const [shownDoc, setShownDoc] = useState(docId);
  if (shownDoc !== docId) {
    setShownDoc(docId);
    setHighlights({});
    setActiveId(null);
    setExpanded(false);
  }

  const bump = () => setVersion((v) => v + 1);

  const report = useCallback(
    (failure: RunFailure | null, again: () => void) => {
      if (!failure) return;
      if (failure.limited) {
        toast({
          tone: "warn",
          title: "Demo limit reached",
          body: failure.message,
          action: { label: "Read how it works instead", onClick: () => void navigate("/how-it-works") },
        });
      } else {
        toast({ tone: "danger", title: "That didn't work", body: failure.message, action: { label: "Try again", onClick: again } });
      }
    },
    [toast, navigate],
  );

  function launch(load: () => Promise<{ document: Document }>, nextTab: Tab, qs: string[]) {
    setTab(nextTab);
    setPane("details");
    setQuestions(qs);
    const go = () => {
      void run.start(load).then((failure) => {
        bump();
        report(failure, go);
      });
    };
    setRetry(() => go);
    go();
  }

  function pickSample(s: Sample) {
    launch(() => api.loadSample(s.sample_id), "results", s.suggested_questions);
  }

  function uploadFile(f: File) {
    const maxMb = status?.limits.max_upload_mb ?? 5;
    if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") {
      toast({ tone: "warn", title: "That isn't a PDF", body: "Only PDF files can be processed here." });
      return;
    }
    if (f.size > maxMb * 1024 * 1024) {
      toast({
        tone: "warn",
        title: "That file is too large",
        body: `The limit is ${maxMb} MB. Try a smaller PDF, or one of the samples.`,
      });
      return;
    }
    launch(() => api.upload(f), "results", GENERIC_QUESTIONS);
  }

  function open(d: Document, t: Tab = "results") {
    launch(() => Promise.resolve({ document: d }), t, GENERIC_QUESTIONS);
  }

  const setSource = useCallback(
    (source: string) => (list: Highlight[]) => setHighlights((h) => ({ ...h, [source]: list })),
    [],
  );
  const onFields = useMemo(() => setSource("fields"), [setSource]);
  const onCitations = useMemo(() => setSource("citations"), [setSource]);
  const onReview = useMemo(() => setSource("review"), [setSource]);
  const onInjection = useMemo(() => setSource("injection"), [setSource]);
  const viewerHighlights = useMemo(
    () => [...(highlights["injection"] ?? []), ...(highlights[TAB_SOURCE[tab]] ?? [])],
    [highlights, tab],
  );

  const locate = useCallback((id: string) => {
    setActiveId(id);
    if (!window.matchMedia(LG).matches) {
      setExpanded(true);
    } else if (!window.matchMedia(WIDE).matches) {
      setPane("page");
      stageRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, []);

  const showWorkspace = doc !== null || run.phase === "uploading";
  const canAsk = doc?.status === "READY" || doc?.status === "NEEDS_REVIEW";
  const finished = doc !== null && run.phase === "done";

  const inspector = doc && (
    <div className="min-w-0 space-y-4">
      {(busy || !finished) && (
        <div className="rounded-xl border border-line bg-surface p-4">
          <Pipeline status={doc.status} processing={busy} failedAt={run.lastStep} />
        </div>
      )}
      {run.error && run.phase === "error" && (
        <ErrorState
          message={run.error}
          action={
            retry && (
              <Button variant="secondary" size="sm" onClick={retry}>
                Try again
              </Button>
            )
          }
        />
      )}
      {finished && doc.status === "FAILED" && (
        <EmptyState
          title="This document couldn't be processed"
          body="It may be empty, a scan with no readable text, or damaged. Try another PDF or one of the samples."
          action={
            <Button variant="secondary" size="sm" onClick={run.reset}>
              Choose another document
            </Button>
          }
        />
      )}
      {finished && doc.status !== "FAILED" && (
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="space-y-4">
          <TabsList aria-label="Document views" className="w-full justify-start">
            <TabsTrigger value="results">
              <ListChecks aria-hidden className="max-sm:hidden" /> Results
            </TabsTrigger>
            <TabsTrigger value="ask" aria-label="Ask questions">
              <MessageSquareText aria-hidden className="max-sm:hidden" /> <span className="sm:hidden">Ask</span>
              <span className="max-sm:hidden">Ask questions</span>
            </TabsTrigger>
            <TabsTrigger value="review">
              <ClipboardCheck aria-hidden className="max-sm:hidden" /> Review
              {doc.status === "NEEDS_REVIEW" && (
                <span className="size-1.5 rounded-full bg-warn" role="img" aria-label="needs attention" />
              )}
            </TabsTrigger>
            <TabsTrigger value="audit" aria-label="Audit trail">
              <History aria-hidden className="max-sm:hidden" /> <span className="sm:hidden">Audit</span>
              <span className="max-sm:hidden">Audit trail</span>
            </TabsTrigger>
          </TabsList>
          {doc.security_flags.includes("prompt_injection_suspected") && (
            <InjectionHighlight documentId={doc.document_id} onLocate={locate} onHighlights={onInjection} />
          )}
          <TabsContent value="results">
            {timings && (
              <details className="group mb-4 rounded-xl border border-line bg-surface">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm text-ink-muted transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
                  <span className="inline-flex items-center gap-2">
                    <span className="size-1.5 rounded-full bg-ok" aria-hidden />
                    Processed in{" "}
                    <span className="num text-ink">{formatMs(Object.values(timings).reduce((a, b) => a + b, 0))}</span>
                    across five steps
                  </span>
                  <ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <div className="border-t border-line p-4">
                  <Pipeline status={doc.status} processing={false} timings={timings} />
                  <p className="mt-3 text-xs text-ink-subtle">Measured on the server, from this run&apos;s audit records.</p>
                </div>
              </details>
            )}
            <FieldsView
              documentId={doc.document_id}
              version={version}
              activeId={activeId}
              onLocate={locate}
              onHighlights={onFields}
            />
          </TabsContent>
          <TabsContent value="ask">
            {canAsk ? (
              <AskPanel
                documentId={doc.document_id}
                suggestions={questions}
                activeId={activeId}
                onLocate={locate}
                onHighlights={onCitations}
              />
            ) : (
              <EmptyState
                title="Questions aren't available"
                body="This document was rejected, so it can't be queried. Open another document to ask questions."
              />
            )}
          </TabsContent>
          <TabsContent value="review">
            <ReviewPanel
              key={`${doc.document_id}-${version}`}
              documentId={doc.document_id}
              activeId={activeId}
              onLocate={locate}
              onHighlights={onReview}
              onResolved={() => {
                void run.reload();
                bump();
                toast({ tone: "ok", title: "Decision saved", body: "It's now part of the audit trail." });
              }}
            />
          </TabsContent>
          <TabsContent value="audit">
            <AuditTrail documentId={doc.document_id} version={version} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );

  return (
    <div className="mx-auto max-w-[1600px] px-4 pb-16 pt-8 sm:px-6 lg:px-8">
      {showWorkspace ? (
        <header className="mb-5 flex min-w-0 items-baseline gap-3">
          <h1 className="shrink-0 text-xl font-semibold tracking-[-0.02em] text-ink">Try it yourself</h1>
          <p className="truncate text-sm text-ink-subtle max-sm:hidden">
            Explore the results, ask questions and act as the reviewer.
          </p>
        </header>
      ) : (
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl space-y-2">
            <Eyebrow>Playground</Eyebrow>
            <h1 className="text-[32px] font-semibold leading-tight tracking-[-0.03em] text-ink">Try it yourself</h1>
            <p className="text-ink-muted">
              Open a sample or upload a PDF. Processing usually takes 5 to 20 seconds; then explore the results, ask
              questions and act as the reviewer.
            </p>
          </div>
        </header>
      )}

      <div className="grid gap-8 lg:grid-cols-[208px_minmax(0,1fr)]">
        <aside className="order-last space-y-6 lg:order-first lg:sticky lg:top-[4.5rem] lg:self-start">
          <DocumentList
            selected={docId}
            onOpen={open}
            onNew={run.reset}
            refreshKey={version}
            busy={busy}
          />
          <div className="border-t border-line pt-5">
            <Allowance />
          </div>
        </aside>

        <div ref={stageRef} className="min-w-0 scroll-mt-20">
          {!showWorkspace ? (
            <div className="space-y-10">
              <section aria-labelledby="samples-heading" className="space-y-4">
                <div className="space-y-1">
                  <h2 id="samples-heading" className="text-lg font-semibold tracking-[-0.01em] text-ink">
                    Start with a sample
                  </h2>
                  <p className="text-sm text-ink-muted">
                    Synthetic documents, each showing one behaviour. Click one to process it.
                  </p>
                </div>
                <SampleGallery onPick={pickSample} disabled={busy} />
              </section>
              <section aria-labelledby="upload-heading" className="space-y-4">
                <h2 id="upload-heading" className="text-lg font-semibold tracking-[-0.01em] text-ink">
                  Or upload your own
                </h2>
                <Callout tone="warn" title="Please don't upload real financial documents">
                  This is a public demo. Your files are visible only to your browser session and are deleted after{" "}
                  {status?.limits.retention_hours ?? 24} hours, and documents may be sent to an AI provider (Claude on
                  AWS Bedrock) for processing.
                </Callout>
                <UploadZone onFile={uploadFile} disabled={busy} />
              </section>
            </div>
          ) : (
            <section aria-label="Current document" className="space-y-4">
              {doc ? (
                <DocumentSummary doc={doc} />
              ) : (
                <Skeleton className="h-[68px] rounded-xl" />
              )}
              <Segmented
                label="Show"
                value={pane}
                onChange={setPane}
                className="xl:hidden"
                options={[
                  { value: "details", label: "Results and actions" },
                  { value: "page", label: "Document page" },
                ]}
              />
              <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,440px)]">
                <div className={cn("min-w-0 xl:sticky xl:top-[4.5rem] xl:block", pane === "page" ? "block" : "hidden")}>
                  {doc ? (
                    <DocumentViewer
                      documentId={doc.document_id}
                      pageCount={doc.page_count}
                      filename={doc.filename}
                      hasTextLayer={doc.has_text_layer}
                      highlights={viewerHighlights}
                      activeId={activeId}
                      onActiveChange={setActiveId}
                      expanded={expanded}
                      onExpandedChange={setExpanded}
                      pageAreaClassName="xl:max-h-[calc(100dvh-12rem)]"
                    />
                  ) : (
                    <ViewerPlaceholder busy />
                  )}
                </div>
                <div className={cn("min-w-0 xl:block", pane === "details" ? "block" : "hidden")}>
                  {inspector ?? (
                    <div className="space-y-3" role="status" aria-busy="true" aria-label="Uploading">
                      <Skeleton className="h-24 rounded-xl" />
                      <Skeleton className="h-64 rounded-xl" />
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
