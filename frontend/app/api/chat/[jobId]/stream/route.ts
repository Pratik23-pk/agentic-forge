import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

import { BackendError, getJob } from "@/lib/backend/client";
import type { ForgeMessage } from "@/lib/contract";
import { streamJob } from "@/lib/gateway/stream";

/**
 * Re-attaches to a job (page reload, or continuing after an approval). Always
 * sends the current snapshot, then keeps streaming while the job is live. A
 * job can reach its next checkpoint before the client re-attaches, so a
 * finished-looking job must still deliver its latest state.
 */
export async function GET(request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  let job;
  try {
    job = await getJob(jobId, request.signal);
  } catch (error) {
    const status = error instanceof BackendError ? error.status : 502;
    return Response.json({ error: (error as Error).message }, { status });
  }
  const stream = createUIMessageStream<ForgeMessage>({
    execute: ({ writer }) =>
      streamJob({ writer, jobId, initialJob: job, fetchJob: getJob, signal: request.signal }),
    onError: (error) => (error instanceof Error ? error.message : "Lost contact with the build."),
  });
  return createUIMessageStreamResponse({ stream });
}
