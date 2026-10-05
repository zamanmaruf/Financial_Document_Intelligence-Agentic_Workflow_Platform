import { useEffect, useState } from "react";

import { api, type WorkflowStatus } from "@/api/client";
import { stepTimings } from "@/lib/plain";

type Timings = Partial<Record<WorkflowStatus, number>>;

/** Server-measured step durations for a finished run (read from its audit records). */
export function useStepTimings(documentId: string | null | undefined, finished: boolean): Timings | undefined {
  const [state, setState] = useState<{ id: string; timings: Timings } | null>(null);

  useEffect(() => {
    if (!documentId || !finished) return;
    let alive = true;
    api
      .audit(documentId)
      .then((a) => alive && setState({ id: documentId, timings: stepTimings(a.events) }))
      .catch(() => undefined); // timings are a nicety; the pipeline still shows each step's state
    return () => {
      alive = false;
    };
  }, [documentId, finished]);

  return state && state.id === documentId && finished ? state.timings : undefined;
}
