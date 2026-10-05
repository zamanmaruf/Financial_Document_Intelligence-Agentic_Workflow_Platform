import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Document = components["schemas"]["DocumentResponse"];
export type Extractions = components["schemas"]["ExtractionsResponse"];
export type Extraction = components["schemas"]["ExtractionResult"];
export type Entity = components["schemas"]["ExtractedEntity"];
export type Answer = components["schemas"]["AskResponse"];
export type Citation = components["schemas"]["Citation"];
export type Review = components["schemas"]["ReviewResponse"];
export type AuditEvent = components["schemas"]["AuditEvent"];
export type Sample = components["schemas"]["DemoSampleResponse"];
export type DemoStatus = components["schemas"]["DemoStatusResponse"];
export type WorkflowStatus = Document["status"];
export type LocateQuery = components["schemas"]["LocateQueryBody"];
export type LocateResponse = components["schemas"]["LocateResponse"];
export type HighlightRect = components["schemas"]["HighlightRect"];

// Same origin as the site: the API and the static build are served by one FastAPI app.
const client = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  readonly retryAfterS: number | null;

  constructor(status: number, type: string, message: string, retryAfterS: number | null) {
    super(message);
    this.status = status;
    this.type = type;
    this.retryAfterS = retryAfterS;
  }
}

interface ErrorBody {
  error?: { type?: string; message?: string };
  detail?: unknown;
}

function toError(response: Response, body: unknown): ApiError {
  const e = (body ?? {}) as ErrorBody;
  const retry = response.headers.get("Retry-After");
  const message =
    e.error?.message ?? (response.status === 422 ? "The request was not valid." : response.statusText);
  return new ApiError(
    response.status,
    e.error?.type ?? `http_${response.status}`,
    message || "Something went wrong.",
    retry ? Number(retry) : null,
  );
}

let session: Promise<void> | null = null;

export function ensureSession(): Promise<void> {
  session ??= client.POST("/demo/session").then(({ error, response }) => {
    if (error !== undefined || !response.ok) {
      session = null;
      throw toError(response, error);
    }
  });
  return session;
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Run an API call inside a visitor session, starting (or restarting) the session as needed. */
async function call<T>(fn: () => Promise<Result<T>>): Promise<T> {
  await ensureSession();
  let r = await fn();
  if (r.response.status === 401) {
    session = null; // the cookie expired or was cleared
    await ensureSession();
    r = await fn();
  }
  if (!r.response.ok || r.data === undefined) throw toError(r.response, r.error);
  return r.data;
}

export const api = {
  status: async (): Promise<DemoStatus> => {
    const { data, error, response } = await client.GET("/demo/status");
    if (!data) throw toError(response, error);
    return data;
  },
  samples: async (): Promise<Sample[]> => {
    const { data, error, response } = await client.GET("/demo/samples");
    if (!data) throw toError(response, error);
    return data;
  },
  sampleFileUrl: (sampleId: string): string => `/demo/samples/${encodeURIComponent(sampleId)}/file`,
  loadSample: (sampleId: string) =>
    call(() => client.POST("/demo/samples/{sample_id}", { params: { path: { sample_id: sampleId } } })),
  upload: (file: File) =>
    call(() =>
      client.POST("/documents/upload", {
        // openapi-fetch serialises JSON by default; uploads need multipart form data
        body: { file: file as unknown as string },
        bodySerializer: (body) => {
          const form = new FormData();
          form.append("file", body.file as unknown as Blob);
          return form;
        },
      }),
    ),
  documents: () => call(() => client.GET("/documents")),
  document: (id: string) =>
    call(() => client.GET("/documents/{document_id}", { params: { path: { document_id: id } } })),
  processInBackground: (id: string) =>
    call(() =>
      client.POST("/documents/{document_id}/process/background", {
        params: { path: { document_id: id } },
      }),
    ),
  extractions: (id: string) =>
    call(() =>
      client.GET("/documents/{document_id}/extractions", { params: { path: { document_id: id } } }),
    ),
  audit: (id: string) =>
    call(() =>
      client.GET("/documents/{document_id}/audit", { params: { path: { document_id: id } } }),
    ),
  verifyAudit: (id: string) =>
    call(() =>
      client.GET("/documents/{document_id}/audit/verify", {
        params: { path: { document_id: id } },
      }),
    ),
  /** Same-origin URL of a rendered page; the browser sends the session cookie with it. */
  pageImageUrl: (id: string, page: number): string =>
    `/documents/${encodeURIComponent(id)}/pages/${page}/image`,
  locate: (id: string, queries: LocateQuery[]) =>
    call(() =>
      client.POST("/documents/{document_id}/locate", {
        params: { path: { document_id: id } },
        body: { queries },
      }),
    ),
  ask: (id: string, question: string) =>
    call(() =>
      client.POST("/documents/{document_id}/ask", {
        params: { path: { document_id: id } },
        body: { question },
      }),
    ),
  reviews: (documentId?: string) =>
    call(() =>
      client.GET("/reviews", {
        params: { query: documentId ? { document_id: documentId } : {} },
      }),
    ),
  approve: (reviewId: string, comment?: string) =>
    call(() =>
      client.POST("/reviews/{review_id}/approve", {
        params: { path: { review_id: reviewId } },
        body: { comment: comment ?? null },
      }),
    ),
  reject: (reviewId: string, comment?: string) =>
    call(() =>
      client.POST("/reviews/{review_id}/reject", {
        params: { path: { review_id: reviewId } },
        body: { comment: comment ?? null },
      }),
    ),
  correct: (reviewId: string, corrections: Record<string, unknown>, comment?: string) =>
    call(() =>
      client.POST("/reviews/{review_id}/correct", {
        params: { path: { review_id: reviewId } },
        body: { corrections, comment: comment ?? null },
      }),
    ),
};

/** Friendly sentence for an error, suitable for a non-technical reader. */
export function friendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      const wait = err.retryAfterS ? ` Try again in about ${humanWait(err.retryAfterS)}.` : "";
      return `You've reached the demo limit (${err.message.replace("demo limit reached: ", "")}).${wait}`;
    }
    if (err.status === 422) return err.message.charAt(0).toUpperCase() + err.message.slice(1) + ".";
    if (err.status === 404) return "That item no longer exists. Demo data is deleted after 24 hours.";
    if (err.status >= 500) return "The service had a problem. Please try again in a moment.";
    return err.message;
  }
  return "Couldn't reach the service. Check your connection and try again.";
}

export function humanWait(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} seconds`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} minutes`;
  return `${Math.round(seconds / 3600)} hours`;
}
