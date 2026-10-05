import type { UIMessageStreamWriter } from "ai";

import type { BackendJob } from "@/lib/backend/types";
import { BackendError } from "@/lib/backend/client";
import type { ForgeMessage } from "@/lib/contract";
import { isLive, jobToParts } from "./translate";

interface StreamJobOptions {
  writer: UIMessageStreamWriter<ForgeMessage>;
  jobId: string;
  fetchJob: (jobId: string, signal?: AbortSignal) => Promise<BackendJob>;
  /** Skips the first fetch when the caller already has the job (e.g. just created it). */
  initialJob?: BackendJob;
  signal?: AbortSignal;
  intervalMs?: number;
  maxConsecutiveErrors?: number;
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

function defaultSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Streams a job as one assistant message. Opens with the full snapshot, then
 * writes only parts whose data changed. Because every part has a stable id
 * and the message id is derived from the job, re-attaching to the same job
 * rebuilds the message exactly instead of duplicating it.
 */
export async function streamJob({
  writer,
  jobId,
  fetchJob,
  initialJob,
  signal,
  intervalMs = 1000,
  maxConsecutiveErrors = 3,
  sleep = defaultSleep,
}: StreamJobOptions): Promise<void> {
  const written = new Map<string, string>();
  let failures = 0;
  let started = false;
  let job: BackendJob | undefined = initialJob;

  while (!signal?.aborted) {
    if (!job) {
      try {
        job = await fetchJob(jobId, signal);
        failures = 0;
      } catch (error) {
        if (signal?.aborted) return;
        failures += 1;
        const fatal = error instanceof BackendError && error.status === 404;
        if (fatal || failures >= maxConsecutiveErrors) {
          writer.write({
            type: "error",
            errorText: error instanceof Error ? error.message : "Lost contact with the build.",
          });
          return;
        }
        await sleep(intervalMs, signal);
        continue;
      }
    }

    if (!started) {
      const basedOn = job.request.metadata?.based_on_job_id;
      writer.write({
        type: "start",
        messageId: `job-${job.job_id}`,
        messageMetadata: {
          jobId: job.job_id,
          projectId: job.request.project_id,
          ...(typeof basedOn === "string" ? { basedOnJobId: basedOn } : {}),
        },
      });
      started = true;
    }

    for (const part of jobToParts(job)) {
      const serialized = JSON.stringify(part.data);
      if (written.get(part.id) === serialized) continue;
      written.set(part.id, serialized);
      writer.write(part);
    }

    if (!isLive(job)) {
      writer.write({ type: "finish" });
      return;
    }

    job = undefined;
    await sleep(intervalMs, signal);
  }
}
