import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

import { createJob, getJob } from "@/lib/backend/client";
import type { BackendJob } from "@/lib/backend/types";
import type { ForgeMessage } from "@/lib/contract";
import { buildFollowUpPrompt, lastUserText } from "@/lib/gateway/prompt";
import { streamJob } from "@/lib/gateway/stream";

interface ChatRequest {
  messages: ForgeMessage[];
  projectName?: string;
  capabilityId?: string;
  basedOnJobId?: string;
}

/**
 * Starts a build from the latest user message and streams it. A follow-up in
 * an existing project (basedOnJobId) builds a new version from the original
 * request plus the change, because the backend cannot patch a project yet.
 */
export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as ChatRequest | null;
  const text = body ? lastUserText(body.messages ?? []) : "";
  if (!body || !text) {
    return Response.json({ error: "Describe what you want to build." }, { status: 400 });
  }

  const stream = createUIMessageStream<ForgeMessage>({
    execute: async ({ writer }) => {
      let parent: BackendJob | undefined;
      if (body.basedOnJobId) parent = await getJob(body.basedOnJobId, request.signal);

      // Versions keep the first request and the list of changes, so each new
      // version composes from those instead of wrapping the previous prompt.
      const parentMeta = parent?.request.metadata ?? {};
      const originalPrompt =
        typeof parentMeta.original_prompt === "string" ? parentMeta.original_prompt : parent?.request.prompt;
      const changes = [
        ...(Array.isArray(parentMeta.changes) ? parentMeta.changes.filter((c): c is string => typeof c === "string") : []),
        ...(parent ? [text] : []),
      ];

      const metadata: Record<string, unknown> = {
        display_prompt: text,
        original_prompt: originalPrompt ?? text,
        changes,
      };
      if (body.capabilityId) metadata.capability_id = body.capabilityId;
      if (parent) metadata.based_on_job_id = parent.job_id;

      const job = await createJob(
        {
          prompt: parent && originalPrompt ? buildFollowUpPrompt(originalPrompt, changes) : text,
          project_id: body.projectName?.trim() || parent?.request.project_id,
          metadata,
        },
        request.signal,
      );

      await streamJob({
        writer,
        jobId: job.job_id,
        initialJob: job,
        fetchJob: getJob,
        signal: request.signal,
      });
    },
    onError: (error) => (error instanceof Error ? error.message : "The build could not start."),
  });

  return createUIMessageStreamResponse({ stream });
}
