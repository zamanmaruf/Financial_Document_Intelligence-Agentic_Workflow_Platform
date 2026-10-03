import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Play,
  RotateCcw,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
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
import { Card } from "@/components/ui/card";
import { useDocumentRun, type DocumentRun } from "@/hooks/useDocumentRun";
import { cn } from "@/lib/utils";

const UNANSWERABLE = "What is the CEO's favourite colour?";

interface Step {
  title: string;
  narration: ReactNode;
}

const STEPS: Step[] = [
  {
    title: "Process a clean invoice",
    narration: (
      <>
        Let's start with an ordinary supplier invoice. Press the button and watch each step run
        for real on the server: reading the PDF, identifying it, pulling out the figures, checking
        them and preparing it for questions.
      </>
    ),
  },
  {
    title: "See what it found",
    narration: (
      <>
        Here are the figures it pulled out. Each one shows how sure it is, in words, and whether
        the value was found word-for-word in the document. Click a row to see the{" "}
        <Term k="evidence" /> it was copied from.
      </>
    ),
  },
  {
    title: "Ask a question",
    narration: (
      <>
        Ask about the invoice in plain English. Answers come with <Term k="citation">sources</Term>{" "}
        from the document. Then try the last question, which the invoice can't answer, and see it
        refuse instead of inventing something.
      </>
    ),
  },
  {
    title: "Catch a problem",
    narration: (
      <>
        Now a balance sheet with a mistake in it: total assets are printed as 9,750,000 on one page
        and 9,570,000 on another. Watch what happens when the numbers disagree.
      </>
    ),
  },
  {
    title: "You're the reviewer",
    narration: (
      <>
        The system didn't pick a number. It sent the document to a person, which is you. Check the
        reasons, choose the correct total (the detailed statement adds up to 9,570,000) and approve.
        This is <Term k="review">human review</Term>.
      </>
    ),
  },
  {
    title: "An attack attempt",
    narration: (
      <>
        This invoice hides a sentence telling AI systems to approve a payment to a different
        account and not to flag it. This is called <Term k="injection">prompt injection</Term>.
        Let's see if it works.
      </>
    ),
  },
  {
    title: "The paper trail",
    narration: (
      <>
        Everything you just did was recorded: every processing step, your review decision, who
        made it and when. Each record carries a fingerprint, so editing it later would be
        detected. This is the <Term k="audit">audit trail</Term>. AI calls are logged separately,
        with the prompt version, timing and estimated cost of each one.
      </>
    ),
  },
  {
    title: "That's the tour",
    narration: <>Here's a recap of what you saw, and where to go next.</>,
  },
];

function RunButton({
  run,
  label,
  onStart,
}: {
  run: DocumentRun;
  label: string;
  onStart: () => void;
}) {
  const busy = run.phase === "uploading" || run.phase === "processing";
  if (run.phase === "done") return null;
  return (
    <Button size="lg" onClick={onStart} disabled={busy}>
      {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
      {busy ? (run.phase === "uploading" ? "Uploading…" : "Processing…") : label}
    </Button>
  );
}

function RunView({ run, sampleId }: { run: DocumentRun; sampleId: string }) {
  return (
    <div className="space-y-4">
      <Pipeline
        status={run.doc?.status ?? null}
        processing={run.phase === "processing" || run.phase === "uploading"}
        failedAt={run.lastStep}
      />
      {run.doc && <DocumentSummary doc={run.doc} />}
      {run.error && <ErrorState message={run.error} />}
      <a
        href={api.sampleFileUrl(sampleId)}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-brand hover:underline"
      >
        Open the original PDF <ExternalLink className="size-3.5" aria-hidden />
      </a>
    </div>
  );
}

function NeedsRun({ what, onGo }: { what: string; onGo: () => void }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong p-6 text-center text-sm text-ink-muted">
      Process the {what} first.{" "}
      <button type="button" className="font-medium text-brand hover:underline" onClick={onGo}>
        Go to that step
      </button>
    </div>
  );
}

export function Tour() {
  const [params, setParams] = useSearchParams();
  const parsed = Number(params.get("step") ?? "1");
  const step = Number.isInteger(parsed) && parsed >= 1 && parsed <= STEPS.length ? parsed - 1 : 0;
  const [reviewVersion, setReviewVersion] = useState(0);
  const [auditDoc, setAuditDoc] = useState<"conflict" | "invoice" | "injection">("conflict");
  const headingRef = useRef<HTMLHeadingElement>(null);

  const invoice = useDocumentRun();
  const conflict = useDocumentRun();
  const injection = useDocumentRun();

  const go = (i: number) => setParams(i === 0 ? {} : { step: String(i + 1) });

  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const needsRunFor: Record<number, DocumentRun | undefined> = { 0: invoice, 3: conflict, 5: injection };
  const gate = needsRunFor[step];
  const canGoNext = step < STEPS.length - 1 && (!gate || gate.phase === "done");

  const startInvoice = () => void invoice.start(() => api.loadSample("clean-invoice"));
  const startConflict = () =>
    void conflict.start(
      () => api.loadSample("conflicting-figures"),
      (d: Document) => d.status !== "NEEDS_REVIEW",
    );
  const startInjection = () => void injection.start(() => api.loadSample("hidden-instructions"));

  const current = STEPS[step] ?? { title: "", narration: null };
  const auditRuns = { conflict, invoice, injection };
  const auditTarget = auditRuns[auditDoc].doc ?? conflict.doc ?? invoice.doc ?? injection.doc;

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      {/* progress */}
      <div className="mb-8 space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-brand">
            Step {step + 1} of {STEPS.length}
          </span>
          <Link to="/try" className="text-ink-muted hover:text-ink">
            Skip to the playground
          </Link>
        </div>
        <div
          className="h-2 overflow-hidden rounded-full bg-surface-muted"
          role="progressbar"
          aria-label="Tour progress"
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
          aria-valuenow={step + 1}
        >
          <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
        </div>
        <ol className="hidden flex-wrap gap-1 sm:flex" aria-label="Tour steps">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <button
                type="button"
                onClick={() => go(i)}
                aria-current={i === step ? "step" : undefined}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs",
                  i === step ? "bg-brand text-brand-ink" : "text-ink-muted hover:bg-surface-muted",
                )}
              >
                {i + 1}. {s.title}
              </button>
            </li>
          ))}
        </ol>
      </div>

      <Card className="p-5 sm:p-8">
        <h1 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold text-ink outline-none">
          {current.title}
        </h1>
        <p className="mt-2 max-w-2xl leading-relaxed text-ink-muted">{current.narration}</p>

        <div className="mt-6 space-y-5" aria-live="polite">
          {step === 0 && (
            <>
              <RunButton run={invoice} label="Process the invoice" onStart={startInvoice} />
              <RunView run={invoice} sampleId="clean-invoice" />
            </>
          )}

          {step === 1 &&
            (invoice.doc ? (
              <FieldsView documentId={invoice.doc.document_id} />
            ) : (
              <NeedsRun what="invoice" onGo={() => go(0)} />
            ))}

          {step === 2 &&
            (invoice.doc ? (
              <AskPanel
                documentId={invoice.doc.document_id}
                suggestions={["What is the total amount due?", "Who sent this invoice?", UNANSWERABLE]}
              />
            ) : (
              <NeedsRun what="invoice" onGo={() => go(0)} />
            ))}

          {step === 3 && (
            <>
              <RunButton run={conflict} label="Process the balance sheet" onStart={startConflict} />
              <RunView run={conflict} sampleId="conflicting-figures" />
              {conflict.phase === "done" && conflict.doc && (
                <FieldsView documentId={conflict.doc.document_id} />
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
                  onResolved={() => {
                    void conflict.reload();
                    setReviewVersion((v) => v + 1);
                  }}
                />
              </>
            ) : (
              <NeedsRun what="balance sheet" onGo={() => go(3)} />
            ))}

          {step === 5 && (
            <>
              <RunButton run={injection} label="Process the invoice" onStart={startInjection} />
              <RunView run={injection} sampleId="hidden-instructions" />
              {injection.phase === "done" && injection.doc && (
                <>
                  <InjectionHighlight documentId={injection.doc.document_id} />
                  <FieldsView documentId={injection.doc.document_id} />
                </>
              )}
            </>
          )}

          {step === 6 &&
            (auditTarget ? (
              <>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Choose a document">
                  {(
                    [
                      ["conflict", "Balance sheet"],
                      ["invoice", "Clean invoice"],
                      ["injection", "Invoice with hidden instructions"],
                    ] as const
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      disabled={!auditRuns[key].doc}
                      aria-pressed={auditDoc === key}
                      onClick={() => setAuditDoc(key)}
                      className={cn(
                        "rounded-full border px-3 py-1.5 text-sm disabled:opacity-40",
                        auditDoc === key ? "border-brand bg-brand-soft text-brand" : "border-line-strong text-ink",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <AuditTrail documentId={auditTarget.document_id} version={reviewVersion} />
              </>
            ) : (
              <NeedsRun what="invoice" onGo={() => go(0)} />
            ))}

          {step === 7 && (
            <div className="space-y-6">
              <ul className="space-y-3">
                {[
                  "It read a PDF and pulled out the key figures, each with the exact text it came from.",
                  "It answered a question with sources, and refused one the document couldn't answer.",
                  "It noticed two different totals and asked a person instead of picking one.",
                  "You corrected the value, and your decision became the record.",
                  "It caught instructions hidden in a document and didn't follow them.",
                  "Every step was written to a tamper-evident audit trail.",
                ].map((item) => (
                  <li key={item} className="flex gap-3 text-ink">
                    <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
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
            </div>
          )}
        </div>
      </Card>

      <div className="mt-6 flex items-center justify-between">
        <Button variant="secondary" onClick={() => go(step - 1)} disabled={step === 0}>
          <ArrowLeft aria-hidden /> Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button onClick={() => go(step + 1)} disabled={!canGoNext}>
            Next <ArrowRight aria-hidden />
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => go(0)}>
            <RotateCcw aria-hidden /> Start again
          </Button>
        )}
      </div>
      {gate && gate.phase !== "done" && step < STEPS.length - 1 && (
        <p className="mt-2 text-right text-xs text-ink-subtle">Run this step to continue.</p>
      )}
    </div>
  );
}
