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
