import { ArrowUp, Ban, BookOpenCheck, LocateFixed, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, friendlyError, type Answer } from "@/api/client";
import { ErrorState } from "@/components/States";
import { Term } from "@/components/Term";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { citationHighlightId, citationHighlights, type Highlight } from "@/components/viewer/highlights";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { confidenceWords } from "@/lib/plain";
import { cn } from "@/lib/utils";

function AnswerCard({
  question,
  answer,
  latest,
  activeId,
  onLocate,
}: {
  question: string;
  answer: Answer;
  latest: boolean;
  activeId?: string | null;
  onLocate?: (id: string) => void;
}) {
  const refused = answer.refused;
  return (
    <article className="animate-fade-up space-y-3" data-testid="answer">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md border border-line-strong bg-surface-overlay px-3.5 py-2 text-sm text-ink">
          {question}
        </p>
      </div>
      <div
        className={cn(
          "space-y-3 rounded-2xl rounded-tl-md border p-4",
          refused ? "border-line-strong bg-surface-raised" : "border-line bg-surface",
        )}
      >
        {refused && (
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">
            <Ban className="size-3.5" aria-hidden /> No answer given
          </p>
        )}
        <p className="leading-relaxed text-ink">{answer.answer}</p>
        {refused ? (
          <p className="text-sm text-ink-muted">
            It refused rather than guess
            {answer.refusal_reason !== "insufficient evidence"
              ? "."
              : answer.is_mock
                ? ": no passage in the document matched the question closely enough. The offline engine matches words, so using the document's own labels (such as “vendor” or “amount due”) can help."
                : ": no passage in the document supports an answer."}
            {answer.requires_review && " The question was also logged for a person to look at."}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="brand">{confidenceWords(answer.confidence)}</Badge>
              {answer.groundedness !== null && (
                <Badge tone={answer.groundedness >= 0.8 ? "ok" : "warn"}>
                  <span className="num">{Math.round(answer.groundedness * 100)}%</span>{" "}
                  <Term k="backed">backed by the document</Term>
                </Badge>
              )}
              {answer.requires_review && <Badge tone="warn">Sent to a person to double-check</Badge>}
              {answer.is_mock && <Badge tone="neutral">Offline engine</Badge>}
            </div>
            {answer.citations.length > 0 && (
              <div className="space-y-2">
                <p className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                  <BookOpenCheck className="size-3.5" aria-hidden /> <Term k="citation">Sources</Term>
                  {latest && onLocate && <span className="text-ink-subtle">· click one to see it on the page</span>}
                </p>
                {answer.citations.map((c, i) => {
                  const id = citationHighlightId(answer.answer_id, i);
                  const interactive = latest && onLocate;
                  const body = (
                    <>
                      <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-brand">
                        <span className="num grid size-4 place-items-center rounded bg-brand-soft text-[10px]">{i + 1}</span>
                        Page {c.page_number ?? "?"}
                        {interactive && <LocateFixed className="ml-auto size-3.5 opacity-70" aria-hidden />}
                      </span>
                      <span className="line-clamp-4 font-mono text-[13px] leading-relaxed text-ink">{c.text_snippet}</span>
                    </>
                  );
                  return interactive ? (
                    <button
                      key={c.chunk_id}
                      type="button"
                      aria-pressed={activeId === id}
                      onClick={() => onLocate(id)}
                      className={cn(
                        "block w-full rounded-lg border px-3 py-2 text-left transition-colors",
                        activeId === id
                          ? "border-brand-line bg-brand-soft"
                          : "border-line bg-white/[0.02] hover:border-brand-line",
                      )}
                    >
                      {body}
                    </button>
                  ) : (
                    <blockquote key={c.chunk_id} className="rounded-lg border border-line bg-white/[0.02] px-3 py-2">
                      {body}
                    </blockquote>
                  );
                })}
              </div>
            )}
          </>
        )}
        {answer.warnings.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-xs text-warn">
            {answer.warnings.map((w) => (
              <li key={w}>{w.charAt(0).toUpperCase() + w.slice(1)}</li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

export function AskPanel({
  documentId,
  suggestions,
  onAnswered,
  activeId,
  onLocate,
  onHighlights,
}: {
  documentId: string;
  suggestions: string[];
  onAnswered?: (answer: Answer) => void;
  activeId?: string | null;
  onLocate?: (id: string) => void;
  onHighlights?: (highlights: Highlight[]) => void;
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ q: string; a: Answer }[]>([]);
  const { status, refresh } = useDemoStatus();

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(text);
    setError(null);
    try {
      const a = await api.ask(documentId, text);
      setHistory((h) => [{ q: text, a }, ...h]);
      setQuestion("");
      onHighlights?.(citationHighlights(a.answer_id, a.citations));
      onAnswered?.(a);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(null);
      refresh();
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  const left = status?.questions_remaining;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Suggested questions">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            disabled={busy !== null}
            onClick={() => void ask(s)}
            className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface-raised px-3 py-1.5 text-[13px] text-ink transition-colors hover:border-brand-line hover:bg-brand-soft disabled:opacity-50"
          >
            <Sparkles className="size-3.5 text-brand" aria-hidden />
            {s}
          </button>
        ))}
      </div>
      <form
        onSubmit={submit}
        className="flex items-center gap-2 rounded-2xl border border-line-strong bg-surface p-1.5 pl-4 shadow-card transition-colors focus-within:border-brand-line"
      >
        <label htmlFor={`ask-${documentId}`} className="sr-only">
          Ask a question about this document
        </label>
        <input
          id={`ask-${documentId}`}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={1000}
          placeholder="Ask anything about this document…"
          className="h-9 min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-subtle focus-visible:outline-none"
        />
        <Button type="submit" size="sm" disabled={!question.trim()} loading={busy !== null} aria-label="Ask">
          {busy === null && <ArrowUp aria-hidden />}
          Ask
        </Button>
      </form>
      {left !== null && left !== undefined && (
        <p className="text-xs text-ink-subtle">
          <span className="num">{left}</span> {left === 1 ? "question" : "questions"} left today
        </p>
      )}
      {error && <ErrorState message={error} />}
      <div aria-live="polite" className="space-y-5">
        {busy && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-md border border-line-strong bg-surface-overlay px-3.5 py-2 text-sm text-ink">
                {busy}
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-md border border-line bg-surface p-4 text-sm text-ink-muted">
              <span className="flex gap-1" aria-hidden>
                <span className="size-1.5 animate-pulse-soft rounded-full bg-brand" />
                <span className="size-1.5 animate-pulse-soft rounded-full bg-brand [animation-delay:200ms]" />
                <span className="size-1.5 animate-pulse-soft rounded-full bg-brand [animation-delay:400ms]" />
              </span>
              Finding the relevant passages and writing an answer (a few seconds)…
            </div>
          </div>
        )}
        {history.map(({ q, a }, i) => (
          <AnswerCard
            key={a.answer_id}
            question={q}
            answer={a}
            latest={i === 0}
            activeId={activeId}
            onLocate={onLocate}
          />
        ))}
      </div>
    </div>
  );
}
