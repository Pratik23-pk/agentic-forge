/**
 * Browser calls to the Python API through the /api fallback rewrite. Job
 * state never comes from here: it streams through the chat gateway.
 */
import { describeBackendError } from "@/lib/backend/errors";
import type {
  BackendFileListing,
  BackendJob,
  BackendPreview,
  BackendProviderStatus,
} from "@/lib/backend/types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: init.body ? { "content-type": "application/json", ...init.headers } : init.headers,
    });
  } catch {
    throw new ApiError("The build service is unreachable. Start the backend and try again.", 0, null);
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(describeBackendError(response.status, body), response.status, body);
  }
  return response;
}

const json = async <T>(path: string, init?: RequestInit) => (await request(path, init)).json() as Promise<T>;
const job = (jobId: string) => `/api/jobs/${encodeURIComponent(jobId)}`;

export const queryKeys = {
  jobs: ["jobs"] as const,
  files: (jobId: string) => ["files", jobId] as const,
  file: (jobId: string, path: string) => ["file", jobId, path] as const,
  preview: (jobId: string) => ["preview", jobId] as const,
  providers: ["providers"] as const,
};

export const listJobs = () => json<BackendJob[]>("/api/jobs");

export const listFiles = (jobId: string) => json<BackendFileListing>(`${job(jobId)}/files`);

export async function readFile(jobId: string, path: string): Promise<string> {
  return (await request(`${job(jobId)}/files/content?path=${encodeURIComponent(path)}`)).text();
}

export class ConflictError extends ApiError {
  constructor(
    message: string,
    readonly currentSha256: string,
  ) {
    super(message, 409, null);
    this.name = "ConflictError";
  }
}

export async function writeFile(
  jobId: string,
  path: string,
  content: string,
  expectedSha256: string,
): Promise<{ path: string; size: number; sha256: string }> {
  try {
    return await json(`${job(jobId)}/files/content?path=${encodeURIComponent(path)}`, {
      method: "PUT",
      body: JSON.stringify({ content, expected_sha256: expectedSha256 }),
    });
  } catch (error) {
    const detail = (error as ApiError).body as { detail?: { current_sha256?: string } } | null;
    if (error instanceof ApiError && error.status === 409 && detail?.detail?.current_sha256) {
      throw new ConflictError(error.message, detail.detail.current_sha256);
    }
    throw error;
  }
}

/** Null when no preview has been started for this job. */
export async function getPreview(jobId: string): Promise<BackendPreview | null> {
  try {
    return await json<BackendPreview>(`${job(jobId)}/preview`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Blocks until the sandbox is running or fails; can take minutes on first start. */
export const startPreview = (jobId: string) =>
  json<BackendPreview>(`${job(jobId)}/preview`, { method: "POST" });

export const stopPreview = (jobId: string) =>
  json<BackendPreview>(`${job(jobId)}/preview`, { method: "DELETE" });

export async function previewLogs(jobId: string): Promise<string> {
  return (await request(`${job(jobId)}/preview/logs`)).text();
}

export const submitFeedback = (
  jobId: string,
  decision: "approve" | "request_changes",
  message?: string,
) =>
  json<BackendJob>(`${job(jobId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({ decision, ...(message ? { message } : {}) }),
  });

export const listProviders = () => json<BackendProviderStatus[]>("/api/providers");

export const syncToGitHub = (
  jobId: string,
  payload: { owner: string; repository: string; branch: string },
) =>
  json<{ repository_url: string; branch: string; pull_request_url: string | null }>(
    `/api/providers/jobs/${encodeURIComponent(jobId)}/github/sync`,
    { method: "POST", body: JSON.stringify({ ...payload, create_pull_request: true }) },
  );

export const downloadUrl = (jobId: string) => `${job(jobId)}/download`;
