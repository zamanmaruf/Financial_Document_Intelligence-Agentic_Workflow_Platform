import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileText,
  Play,
  RotateCcw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { api, type Document } from "@/api/client";
import { AskPanel } from "@/components/AskPanel";
import { AuditTrail } from "@/components/AuditTrail";
import { DocumentSummary } from "@/components/DocumentSummary";
import { FieldsView } from "@/components/FieldsView";
import { InjectionHighlight } from "@/components/InjectionHighlight";
import { GITHUB_URL } from "@/components/Layout";
import { Pipeline } from "@/components/Pipeline";
import { ReviewPanel } from "@/components/ReviewPanel";
import { ErrorState } from "@/components/States";
import { Term } from "@/components/Term";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
import { Kbd } from "@/components/ui/kbd";
import { Segmented } from "@/components/ui/segmented";
import { Stepper, type StepperItem } from "@/components/ui/stepper";
import { useToast } from "@/components/ui/toast";
import { DocumentViewer, type Highlight } from "@/components/viewer";
import { useDocumentRun, type DocumentRun } from "@/hooks/useDocumentRun";
import { useStepTimings } from "@/hooks/useStepTimings";
import { cn } from "@/lib/utils";

const UNANSWERABLE = "What is the CEO's favourite colour?";

type Stage = "invoice" | "conflict" | "injection" | null;

interface Step {
  title: string;
  time: string;
  stage: Stage;
  narration: ReactNode;
}

const STEPS: Step[] = [
  {
    title: "Process a clean invoice",
    time: "About 15 seconds",
    stage: "invoice",
    narration: (
      <>
        Let&apos;s start with an ordinary supplier invoice. Press the button and watch each step run
        for real on the server: reading the PDF, identifying it, pulling out the figures, checking
        them and preparing it for questions.
      </>
    ),
  },
  {
    title: "See what it found",
    time: "About 30 seconds",
    stage: "invoice",
    narration: (
      <>
        Here are the figures it pulled out, each with how sure it is, in words. Click a row and the
        document viewer boxes the exact words it was copied from: the <Term k="evidence" />.
      </>
    ),
  },
  {
    title: "Ask a question",
    time: "About 30 seconds",
    stage: "invoice",
    narration: (
      <>
        Ask about the invoice in plain English. Answers come with <Term k="citation">sources</Term>;
        click one to see it on the page. Then try the last question, which the invoice can&apos;t
        answer, and see it refuse instead of inventing something.
      </>
    ),
  },
  {
    title: "Catch a problem",
    time: "About 15 seconds",
    stage: "conflict",
    narration: (
      <>
        Now a balance sheet with a mistake in it: total assets are printed as 9,750,000 on one page
        and 9,570,000 on another. Watch what happens when the numbers disagree.
      </>
    ),
  },
  {
    title: "You're the reviewer",
    time: "About 30 seconds",
    stage: "conflict",
    narration: (
      <>
        The system didn&apos;t pick a number. It sent the document to a person, which is you. Click
        each value to see where it appears, choose the correct total (the detailed statement adds up
        to 9,570,000) and approve. This is <Term k="review">human review</Term>.
      </>
    ),
  },
  {
    title: "An attack attempt",
    time: "About 15 seconds",
    stage: "injection",
    narration: (
      <>
        This invoice hides a sentence telling AI systems to approve a payment to a different account
        and not to flag it. This is called <Term k="injection">prompt injection</Term>. Let&apos;s see
        if it works.
      </>
    ),
  },
  {
    title: "The paper trail",
    time: "About 20 seconds",
    stage: null,
    narration: (
      <>
        Everything you just did was recorded: every processing step, your review decision, who made
        it and when. Each record carries a fingerprint, so editing it later would be detected. This
        is the <Term k="audit">audit trail</Term>. AI calls are logged separately, with the prompt
        version, timing and estimated cost of each one.
      </>
    ),
  },
  {
    title: "That's the tour",
    time: "",
    stage: null,
    narration: <>Here&apos;s a recap of what you saw, and where to go next.</>,
  },
];

const RECAP = [
  "It read a PDF and pulled out the key figures, each boxed on the page where it was found.",
  "It answered a question with sources, and refused one the document couldn't answer.",
  "It noticed two different totals and asked a person instead of picking one.",
  "You chose the correct value, and your decision became the record.",
  "It caught instructions hidden in a document, boxed them in red and didn't follow them.",
  "Every step was written to a tamper-evident audit trail.",
];

function RunButton({ run, label, onStart }: { run: DocumentRun; label: string; onStart: () => void }) {
  const busy = run.phase === "uploading" || run.phase === "processing";
  if (run.phase === "done") {
    return (
      <p className="flex animate-fade-in items-center gap-2 text-sm text-ok">
        <CheckCircle2 className="size-4" aria-hidden /> Processed. Continue when you&apos;re ready.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <Button size="lg" onClick={onStart} loading={busy} className="w-full sm:w-auto">
        {!busy && <Play aria-hidden />}
        {busy ? (run.phase === "uploading" ? "Uploading…" : "Processing…") : label}
      </Button>
      <p className="text-xs text-ink-subtle">Runs for real on the server. Usually 5 to 20 seconds.</p>
    </div>
  );
}

function RunView({ run, sampleId }: { run: DocumentRun; sampleId: string }) {
  const timings = useStepTimings(run.doc?.document_id, run.phase === "done");
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <Pipeline
          status={run.doc?.status ?? null}
          processing={run.phase === "processing" || run.phase === "uploading"}
          failedAt={run.lastStep}
          timings={timings}
        />
        {timings && (
          <p className="mt-4 border-t border-line pt-3 text-xs text-ink-subtle">
            Step times measured on the server, from the audit records of this run.
          </p>
        )}
      </div>
      {run.doc && <DocumentSummary doc={run.doc} />}
      {run.error && <ErrorState message={run.error} />}
      <a
        href={api.sampleFileUrl(sampleId)}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted transition-colors hover:text-ink"
      >
        Open the original PDF <ExternalLink className="size-3.5" aria-hidden />
      </a>
    </div>
  );
}

function NeedsRun({ what, onGo }: { what: string; onGo: () => void }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-surface/60 p-8 text-center text-sm text-ink-muted">
      <p>Process the {what} first.</p>
      <Button variant="secondary" size="sm" className="mt-3" onClick={onGo}>
        Go to that step
      </Button>
    </div>
  );
}

function ViewerPlaceholder({ busy }: { busy: boolean }) {
  return (
    <div className="flex aspect-[1/1.2] max-h-[70vh] w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-line-strong bg-surface/50 p-8 text-center">
      <span className="grid size-11 place-items-center rounded-xl border border-line-strong bg-surface-raised text-ink-muted">
        <FileText className="size-5" aria-hidden />
      </span>
      <p className="text-sm font-medium text-ink">{busy ? "Loading the document…" : "The document appears here"}</p>
      <p className="max-w-xs text-xs text-ink-muted">
        Once it&apos;s loaded you can see every page, with the values it found boxed in place.
      </p>
    </div>
  );
}

export function Tour() {
  const [params, setParams] = useSearchParams();
  const parsed = Number(params.get("step") ?? "1");
  const step = Number.isInteger(parsed) && parsed >= 1 && parsed <= STEPS.length ? parsed - 1 : 0;
  const [reviewVersion, setReviewVersion] = useState(0);
  const [reviewed, setReviewed] = useState(false);
  const [answered, setAnswered] = useState(false);
  const [auditDoc, setAuditDoc] = useState<"conflict" | "invoice" | "injection">("conflict");
  const [highlights, setHighlights] = useState<Record<string, Highlight[]>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showDoc, setShowDoc] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { toast } = useToast();

  const invoice = useDocumentRun();
  const conflict = useDocumentRun();
  const injection = useDocumentRun();

  // New step: clear the previous step's boxes and selection (state derived during render).
  const [shownStep, setShownStep] = useState(step);
  if (shownStep !== step) {
    setShownStep(step);
    setHighlights({});
    setActiveId(null);
  }

  const go = useCallback(
    (i: number) => setParams(i === 0 ? {} : { step: String(i + 1) }),
    [setParams],
  );

  useEffect(() => {
    window.scrollTo({ top: 0 });
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  const gates: Record<number, DocumentRun | undefined> = { 0: invoice, 3: conflict, 5: injection };
  const gate = gates[step];
  const last = step === STEPS.length - 1;
  const canGoNext = !last && (!gate || gate.phase === "done");
  const actionDone: Record<number, boolean> = {
    0: invoice.phase === "done",
    1: activeId !== null,
    2: answered,
    3: conflict.phase === "done",
    4: reviewed,
    5: injection.phase === "done",
    6: true,
  };
  const nudge = canGoNext && (actionDone[step] ?? false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='group'], [role='tablist'], [role='region']")) return;
      if (e.key === "ArrowRight" && canGoNext) go(step + 1);
      else if (e.key === "ArrowLeft" && step > 0) go(step - 1);
      else if (e.key === "Enter" && canGoNext && (target === document.body || target === headingRef.current)) {
        e.preventDefault();
        go(step + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, canGoNext, go]);

  const startInvoice = () => void invoice.start(() => api.loadSample("clean-invoice"));
  const startConflict = () =>
    void conflict.start(
      () => api.loadSample("conflicting-figures"),
      (d: Document) => d.status !== "NEEDS_REVIEW",
    );
  const startInjection = () => void injection.start(() => api.loadSample("hidden-instructions"));

  const setSource = useCallback(
    (source: string) => (list: Highlight[]) => setHighlights((h) => ({ ...h, [source]: list })),
    [],
  );
  const onFields = useMemo(() => setSource("fields"), [setSource]);
  const onCitations = useMemo(() => setSource("citations"), [setSource]);
  const onReview = useMemo(() => setSource("review"), [setSource]);
  const onInjection = useMemo(() => setSource("injection"), [setSource]);
  const viewerHighlights = useMemo(() => Object.values(highlights).flat(), [highlights]);
  const locate = useCallback((id: string) => {
    setActiveId(id);
    setShowDoc(true);
  }, []);

  const current: Step = STEPS[step] ?? { title: "", time: "", stage: null, narration: null };
  const auditRuns = { conflict, invoice, injection };
  const auditTarget = auditRuns[auditDoc].doc ?? conflict.doc ?? invoice.doc ?? injection.doc;
  const stageRun = current.stage ? { invoice, conflict, injection }[current.stage] : null;
  const stageDoc = stageRun?.doc ?? null;

  const rail: StepperItem[] = STEPS.map((s, i) => ({
    title: s.title,
    state: i === step ? "current" : i < step ? "done" : "upcoming",
  }));

  async function copyLink() {
    const url = `${window.location.origin}/tour`;
    try {
      await navigator.clipboard.writeText(url);
      toast({ tone: "ok", title: "Link copied", body: url });
    } catch {
      toast({ tone: "info", title: "Copy this link", body: url });
    }
  }

  const action =
    step === 0 ? (
      <RunButton run={invoice} label="Process the invoice" onStart={startInvoice} />
    ) : step === 3 ? (
      <RunButton run={conflict} label="Process the balance sheet" onStart={startConflict} />
    ) : step === 5 ? (
      <RunButton run={injection} label="Process the invoice" onStart={startInjection} />
    ) : null;

  return (
    <div className="mx-auto grid max-w-[1600px] lg:grid-cols-[minmax(360px,420px)_minmax(0,1fr)]">
      {/* story */}
      <aside className="border-line lg:sticky lg:top-14 lg:flex lg:h-[calc(100dvh-3.5rem)] lg:flex-col lg:border-r">
        <div className="flex-1 space-y-6 px-4 pb-6 pt-6 sm:px-6 lg:overflow-y-auto">
          <div className="flex items-center justify-between gap-3">
            <Eyebrow>Guided tour</Eyebrow>
            <Link to="/try" className="text-xs text-ink-muted transition-colors hover:text-ink">
              Skip to the playground
            </Link>
          </div>

          <div className="space-y-2 lg:hidden">
            <div
              className="flex gap-1"
              role="progressbar"
              aria-label="Tour progress"
              aria-valuemin={1}
              aria-valuemax={STEPS.length}
              aria-valuenow={step + 1}
            >
              {STEPS.map((s, i) => (
                <span
                  key={s.title}
                  className={cn(
                    "h-1 flex-1 rounded-full transition-colors duration-300",
                    i < step ? "bg-brand/70" : i === step ? "bg-ink" : "bg-white/10",
                  )}
                />
              ))}
            </div>
          </div>

          <Stepper items={rail} onSelect={go} label="Tour steps" className="hidden lg:block" />

          <div key={step} className="animate-fade-up space-y-4 lg:border-t lg:border-line lg:pt-6">
            <p className="num text-xs text-ink-subtle">
              Step {step + 1} of {STEPS.length}
              {current.time && ` · ${current.time}`}
            </p>
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-[28px] font-semibold leading-tight tracking-[-0.025em] text-ink outline-none"
            >
              {current.title}
            </h1>
            <p className="leading-relaxed text-ink-muted">{current.narration}</p>
            {action && <div className="pt-1">{action}</div>}
          </div>
        </div>

        <div data-tour-bar className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-canvas/85 px-4 py-3 backdrop-blur-xl [padding-bottom:max(0.75rem,env(safe-area-inset-bottom))] sm:px-6 lg:static lg:bg-transparent lg:backdrop-blur-none">
          <div className="flex items-center justify-between gap-3">
            <Button variant="secondary" onClick={() => go(step - 1)} disabled={step === 0}>
              <ArrowLeft aria-hidden /> Back
            </Button>
            <span className="hidden items-center gap-1 text-[11px] text-ink-subtle xl:flex" aria-hidden>
              <Kbd>←</Kbd>
              <Kbd>→</Kbd>
              to move
            </span>
            {!last ? (
              <Button onClick={() => go(step + 1)} disabled={!canGoNext} className={cn(nudge && "animate-nudge")}>
                Continue <ArrowRight aria-hidden />
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => go(0)}>
                <RotateCcw aria-hidden /> Start again
              </Button>
            )}
          </div>
          {gate && gate.phase !== "done" && !last && (
            <p className="mt-1.5 text-right text-[11px] text-ink-subtle">Run this step to continue.</p>
          )}
        </div>
      </aside>

      {/* stage */}
      <section aria-label="Demo" className="min-w-0 px-4 pb-28 pt-2 sm:px-6 lg:px-8 lg:pb-12 lg:pt-8">
        <div
          key={step}
          className={cn(
            "animate-fade-in",
            current.stage ? "grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]" : "mx-auto max-w-3xl",
          )}
        >
          <div className="min-w-0 space-y-5" aria-live="polite">
            {step === 0 && <RunView run={invoice} sampleId="clean-invoice" />}

            {step === 1 &&
              (invoice.doc ? (
                <FieldsView
                  documentId={invoice.doc.document_id}
                  activeId={activeId}
                  onLocate={locate}
                  onHighlights={onFields}
                />
              ) : (
                <NeedsRun what="invoice" onGo={() => go(0)} />
              ))}

            {step === 2 &&
              (invoice.doc ? (
                <AskPanel
                  documentId={invoice.doc.document_id}
                  suggestions={["What is the total amount due?", "Who sent this invoice?", UNANSWERABLE]}
                  onAnswered={() => setAnswered(true)}
                  activeId={activeId}
                  onLocate={locate}
                  onHighlights={onCitations}
                />
              ) : (
                <NeedsRun what="invoice" onGo={() => go(0)} />
              ))}

            {step === 3 && (
              <>
                <RunView run={conflict} sampleId="conflicting-figures" />
                {conflict.phase === "done" && conflict.doc && (
                  <FieldsView
                    documentId={conflict.doc.document_id}
                    activeId={activeId}
                    onLocate={locate}
                    onHighlights={onFields}
                  />
                )}
              </>
            )}

            {step === 4 &&
              (conflict.doc ? (
                <>
                  <DocumentSummary doc={conflict.doc} />
                  <ReviewPanel
                    key={`${conflict.doc.document_id}-${reviewVersion}`}
                    documentId={conflict.doc.document_id}
                    activeId={activeId}
                    onLocate={locate}
                    onHighlights={onReview}
                    onResolved={() => {
                      void conflict.reload();
                      setReviewed(true);
                      setReviewVersion((v) => v + 1);
                    }}
                  />
                </>
              ) : (
                <NeedsRun what="balance sheet" onGo={() => go(3)} />
              ))}

            {step === 5 && (
              <>
                <RunView run={injection} sampleId="hidden-instructions" />
                {injection.phase === "done" && injection.doc && (
                  <>
                    <InjectionHighlight
                      documentId={injection.doc.document_id}
                      onLocate={locate}
                      onHighlights={onInjection}
                    />
                    <FieldsView
                      documentId={injection.doc.document_id}
                      activeId={activeId}
                      onLocate={locate}
                      onHighlights={onFields}
                    />
                  </>
                )}
              </>
            )}

            {step === 6 &&
              (auditTarget ? (
                <>
                  <Segmented
                    label="Choose a document"
                    value={auditDoc}
                    onChange={setAuditDoc}
                    options={[
                      { value: "conflict", label: "Balance sheet", disabled: !conflict.doc },
                      { value: "invoice", label: "Clean invoice", disabled: !invoice.doc },
                      { value: "injection", label: "Invoice with hidden instructions", disabled: !injection.doc },
                    ]}
                  />
                  <AuditTrail documentId={auditTarget.document_id} version={reviewVersion} />
                </>
              ) : (
                <NeedsRun what="invoice" onGo={() => go(0)} />
              ))}

            {step === 7 && (
              <div className="space-y-8">
                <ul className="space-y-1">
                  {RECAP.map((item, i) => (
                    <li
                      key={item}
                      className="flex animate-fade-up gap-3 rounded-xl px-1 py-2.5 text-[15px] text-ink"
                      style={{ animationDelay: `${i * 70}ms` }}
                    >
                      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden />
                      {item}
                    </li>
                  ))}
                </ul>
                <div className="relative overflow-hidden rounded-2xl border border-line bg-surface p-6">
                  <div aria-hidden className="glow-hero absolute inset-0 opacity-70" />
                  <div className="relative space-y-4">
                    <p className="text-lg font-semibold text-ink">Where to next?</p>
                    <div className="flex flex-wrap gap-3">
                      <Button asChild size="lg">
                        <Link to="/try">Try your own document</Link>
                      </Button>
                      <Button asChild size="lg" variant="secondary">
                        <Link to="/how-it-works">How it works</Link>
                      </Button>
                      <Button asChild size="lg" variant="ghost">
                        <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                          Read the code
                        </a>
                      </Button>
                    </div>
                    <button
                      type="button"
                      onClick={() => void copyLink()}
                      className="inline-flex items-center gap-1.5 text-sm text-ink-muted transition-colors hover:text-ink"
                    >
                      <Copy className="size-3.5" aria-hidden /> Copy a link to this tour
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {current.stage && (
            <div className="min-w-0 xl:sticky xl:top-[4.5rem]">
              <button
                type="button"
                onClick={() => setShowDoc((v) => !v)}
                aria-expanded={showDoc}
                className="mb-3 flex w-full items-center justify-between rounded-xl border border-line bg-surface px-4 py-3 text-sm font-medium text-ink lg:hidden"
              >
                <span className="inline-flex items-center gap-2">
                  <FileText className="size-4 text-ink-muted" aria-hidden />
                  {showDoc ? "Hide the document" : "Show the document"}
                </span>
                <span className="text-xs text-ink-subtle">{viewerHighlights.length > 0 ? `${viewerHighlights.length} boxed` : ""}</span>
              </button>
              <div className={cn(showDoc ? "block" : "hidden", "lg:block")}>
                {stageDoc ? (
                  <DocumentViewer
                    documentId={stageDoc.document_id}
                    pageCount={stageDoc.page_count}
                    filename={stageDoc.filename}
                    hasTextLayer={stageDoc.has_text_layer}
                    highlights={viewerHighlights}
                    activeId={activeId}
                    onActiveChange={setActiveId}
                    pageAreaClassName="xl:max-h-[calc(100dvh-12.5rem)]"
                  />
                ) : (
                  <ViewerPlaceholder busy={stageRun?.phase === "uploading"} />
                )}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
