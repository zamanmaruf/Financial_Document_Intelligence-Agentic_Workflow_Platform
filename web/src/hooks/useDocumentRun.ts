import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, friendlyError, type Document, type WorkflowStatus } from "@/api/client";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { FINAL_STATUSES } from "@/lib/plain";

export type RunPhase = "idle" | "uploading" | "processing" | "done" | "error";

export interface RunFailure {
  message: string;
  /** The demo allowance (or a rate limit) was reached. */
  limited: boolean;
}

export interface DocumentRun {
  phase: RunPhase;
  doc: Document | null;
  /** Last in-progress status seen before a failure, to show where it stopped. */
  lastStep: WorkflowStatus | undefined;
  error: string | null;
  /**
   * ``reprocessIf`` re-runs processing for a document that was already processed earlier in
   * this session (loading the same sample twice returns the existing copy). Resolves with the
   * error shown to the visitor, or null.
   */
  start: (
    load: () => Promise<{ document: Document }>,
    reprocessIf?: (doc: Document) => boolean,
  ) => Promise<RunFailure | null>;
  /** Re-read the document (after a review decision, for example). */
  reload: () => Promise<void>;
  reset: () => void;
}

const POLL_MS = 600;
const TIMEOUT_MS = 5 * 60_000;

/** Upload (or load a sample), process it in the background and follow its progress. */
export function useDocumentRun(): DocumentRun {
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [doc, setDoc] = useState<Document | null>(null);
  const [lastStep, setLastStep] = useState<WorkflowStatus | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const runId = useRef(0);
  const { refresh } = useDemoStatus();

  useEffect(
    () => () => {
      runId.current += 1; // stop polling on unmount
    },
    [],
  );

  const start = useCallback(
    async (
      load: () => Promise<{ document: Document }>,
      reprocessIf?: (doc: Document) => boolean,
    ): Promise<RunFailure | null> => {
      const id = ++runId.current;
      const alive = () => runId.current === id;
      setError(null);
      setDoc(null);
      setLastStep(undefined);
      setPhase("uploading");
      try {
        const { document } = await load();
        if (!alive()) return null;
        setDoc(document);
        let current = document;
        const needsRun =
          !FINAL_STATUSES.has(document.status) ||
          document.status === "FAILED" ||
          (reprocessIf?.(document) ?? false);
        if (needsRun && !document.processing) {
          setPhase("processing");
          current = await api.processInBackground(document.document_id);
          const deadline = Date.now() + TIMEOUT_MS;
          while (alive() && (current.processing || !FINAL_STATUSES.has(current.status))) {
            if (Date.now() > deadline) throw new Error("timeout");
            setDoc(current);
            if (!FINAL_STATUSES.has(current.status)) setLastStep(current.status);
            await new Promise((r) => window.setTimeout(r, POLL_MS));
            current = await api.document(document.document_id);
          }
        }
        if (!alive()) return null;
        setDoc(current);
        setPhase("done");
        return null;
      } catch (err) {
        if (!alive()) return null;
        const message =
          err instanceof Error && err.message === "timeout"
            ? "This is taking longer than expected. Refresh the page to check on it."
            : friendlyError(err);
        setError(message);
        setPhase("error");
        return { message, limited: err instanceof ApiError && err.status === 429 };
      } finally {
        if (alive()) refresh();
      }
    },
    [refresh],
  );

  const reload = useCallback(async () => {
    if (!doc) return;
    setDoc(await api.document(doc.document_id));
  }, [doc]);

  const reset = useCallback(() => {
    runId.current += 1;
    setPhase("idle");
    setDoc(null);
    setError(null);
    setLastStep(undefined);
  }, []);

  return { phase, doc, lastStep, error, start, reload, reset };
}
