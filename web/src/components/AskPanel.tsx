import { BookOpenCheck, Ban, Loader2, MessageCircleQuestion, Send } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, friendlyError, type Answer } from "@/api/client";
import { ErrorState } from "@/components/States";
import { Term } from "@/components/Term";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { confidenceWords } from "@/lib/plain";

function AnswerCard({ question, answer }: { question: string; answer: Answer }) {
  const refused = answer.refused;
  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-4" data-testid="answer">
      <p className="flex items-start gap-2 text-sm text-ink-muted">
        <MessageCircleQuestion className="mt-0.5 size-4 shrink-0" aria-hidden />
        {question}
      </p>
      <div className={refused ? "rounded-md bg-surface-muted p-3" : ""}>
        {refused && (
          <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            <Ban className="size-3.5" aria-hidden /> No answer given
          </p>
        )}
        <p className="text-ink">{answer.answer}</p>
      </div>
      {refused ? (
        <p className="text-sm text-ink-muted">
          It refused rather than guess
          {answer.refusal_reason === "insufficient evidence"
            ? ": the document doesn't contain this information."
            : "."}
          {answer.requires_review && " The question was also logged for a person to look at."}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Badge tone="brand">{confidenceWords(answer.confidence)}</Badge>
            {answer.groundedness !== null && (
              <Badge tone={answer.groundedness >= 0.8 ? "ok" : "warn"}>
                {Math.round(answer.groundedness * 100)}% <Term k="backed">backed by the document</Term>
              </Badge>
            )}
            {answer.requires_review && <Badge tone="warn">Sent to a person to double-check</Badge>}
            {answer.is_mock && <Badge tone="neutral">Offline engine</Badge>}
          </div>
          {answer.citations.length > 0 && (
            <div className="space-y-2">
              <p className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                <BookOpenCheck className="size-3.5" aria-hidden /> <Term k="citation">Sources</Term>
              </p>
              {answer.citations.map((c) => (
                <blockquote
                  key={c.chunk_id}
                  className="rounded-md border-l-4 border-brand bg-brand-soft/50 px-3 py-2 text-sm"
                >
                  <span className="block text-xs text-brand">Page {c.page_number ?? "?"}</span>
                  <span className="font-mono text-ink">{c.text_snippet}</span>
                </blockquote>
              ))}
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
  );
}

export function AskPanel({
  documentId,
  suggestions,
  onAnswered,
}: {
  documentId: string;
  suggestions: string[];
  onAnswered?: (answer: Answer) => void;
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ q: string; a: Answer }[]>([]);
  const { status, refresh } = useDemoStatus();

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const a = await api.ask(documentId, text);
      setHistory((h) => [{ q: text, a }, ...h]);
      setQuestion("");
      onAnswered?.(a);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" aria-label="Suggested questions">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            disabled={busy}
            onClick={() => void ask(s)}
            className="rounded-full border border-line-strong bg-surface px-3 py-1.5 text-sm text-ink hover:border-brand hover:text-brand disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="flex gap-2">
        <label htmlFor={`ask-${documentId}`} className="sr-only">
          Ask a question about this document
        </label>
        <input
          id={`ask-${documentId}`}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={1000}
          placeholder="Ask anything about this document…"
          className="h-10 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-ink-subtle"
        />
        <Button type="submit" disabled={busy || !question.trim()}>
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
          Ask
        </Button>
      </form>
      {status?.questions_remaining !== null && status?.questions_remaining !== undefined && (
        <p className="text-xs text-ink-subtle">{status.questions_remaining} questions left today</p>
      )}
      {error && <ErrorState message={error} />}
      <div aria-live="polite" className="space-y-3">
        {busy && (
          <div className="flex items-center gap-2 rounded-lg border border-line bg-surface p-4 text-sm text-ink-muted">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Finding the relevant passages and writing an answer…
          </div>
        )}
        {history.map(({ q, a }) => (
          <AnswerCard key={a.answer_id} question={q} answer={a} />
        ))}
      </div>
    </div>
  );
}
