/**
 * Server-side access to the Python API. Used by route handlers and server
 * components; the browser reaches the same API through the /api rewrite.
 */
import type { BackendJob } from "./types";

export function backendUrl(): string {
  return (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

export class BackendError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

/** FastAPI errors arrive as `{ detail: string | { message } | [...] }`. */
export function describeBackendError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === "string") return detail[0].msg;
  if (status === 502 || status === 503) return "The build service is unavailable. Start the backend and try again.";
  return `The build service returned an error (${status}).`;
}

export async function backendFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${backendUrl()}${path}`, {
      cache: "no-store",
      ...init,
      headers: { "content-type": "application/json", ...init.headers },
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new BackendError("The build service is unreachable. Start the backend and try again.", 503);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new BackendError(describeBackendError(response.status, body), response.status);
  return body as T;
}

export function getJob(jobId: string, signal?: AbortSignal): Promise<BackendJob> {
  return backendFetch<BackendJob>(`/api/jobs/${encodeURIComponent(jobId)}`, { signal });
}

export interface CreateJobInput {
  prompt: string;
  project_id?: string;
  metadata: Record<string, unknown>;
}

export function createJob(input: CreateJobInput, signal?: AbortSignal): Promise<BackendJob> {
  return backendFetch<BackendJob>("/api/jobs", {
    method: "POST",
    body: JSON.stringify({ ...input, run_immediately: true }),
    signal,
  });
}

/** The job and the jobs it was based on, oldest first. Stops at missing parents and cycles. */
export async function getJobChain(jobId: string, maxDepth = 10): Promise<BackendJob[]> {
  const chain: BackendJob[] = [];
  const seen = new Set<string>();
  let nextId: string | undefined = jobId;
  while (nextId && !seen.has(nextId) && chain.length < maxDepth) {
    seen.add(nextId);
    let job: BackendJob;
    try {
      job = await getJob(nextId);
    } catch (error) {
      if (chain.length > 0 && error instanceof BackendError && error.status === 404) break;
      throw error;
    }
    chain.unshift(job);
    const parent: unknown = job.request.metadata?.based_on_job_id;
    nextId = typeof parent === "string" ? parent : undefined;
  }
  return chain;
}
