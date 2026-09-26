// @vitest-environment node
import type { UIMessageStreamWriter } from "ai";
import { describe, expect, it, vi } from "vitest";

import { BackendError } from "@/lib/backend/client";
import type { BackendJob } from "@/lib/backend/types";
import type { ForgeMessage } from "@/lib/contract";
import succeeded from "./__fixtures__/succeeded.json";
import { streamJob } from "./stream";
import { jobToParts } from "./translate";

type Chunk = Parameters<UIMessageStreamWriter<ForgeMessage>["write"]>[0];

function recorder() {
  const chunks: Chunk[] = [];
  const writer = {
    write: (chunk: Chunk) => chunks.push(chunk),
    merge: vi.fn(),
    onError: undefined,
  } as unknown as UIMessageStreamWriter<ForgeMessage>;
  return { chunks, writer };
}

function jobWith(status: string, mutate?: (job: BackendJob) => void): BackendJob {
  const job = structuredClone(succeeded) as BackendJob;
  job.status = status;
  mutate?.(job);
  return job;
}

const noSleep = () => Promise.resolve();

describe("streamJob", () => {
  it("opens with start metadata and the full snapshot, then finishes for a terminal job", async () => {
    const { chunks, writer } = recorder();
    const job = jobWith("succeeded");
    await streamJob({ writer, jobId: job.job_id, fetchJob: async () => job, sleep: noSleep });

    expect(chunks[0]).toEqual({
      type: "start",
      messageId: `job-${job.job_id}`,
      messageMetadata: { jobId: job.job_id, projectId: job.request.project_id },
    });
    expect(chunks.slice(1, -1)).toEqual(jobToParts(job));
    expect(chunks.at(-1)).toEqual({ type: "finish" });
  });

  it("writes only changed parts on later polls and stops when the job ends", async () => {
    const { chunks, writer } = recorder();
    const running = jobWith("running");
    const done = jobWith("succeeded");
    const fetchJob = vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(running).mockResolvedValueOnce(done);

    await streamJob({ writer, jobId: running.job_id, fetchJob, sleep: noSleep });

    expect(fetchJob).toHaveBeenCalledTimes(3);
    const firstSnapshot = jobToParts(running).length;
    const changed = chunks.slice(1 + firstSnapshot, -1).map((chunk) => (chunk as { id: string }).id);
    // The identical second poll writes nothing; the final poll writes only what changed.
    expect(changed.length).toBeGreaterThan(0);
    expect(changed.length).toBeLessThan(firstSnapshot);
    expect(changed).toContain("job");
    expect(chunks.at(-1)).toEqual({ type: "finish" });
  });

  it("uses the initial job without fetching it again", async () => {
    const { writer } = recorder();
    const fetchJob = vi.fn();
    const job = jobWith("succeeded");
    await streamJob({ writer, jobId: job.job_id, initialJob: job, fetchJob, sleep: noSleep });
    expect(fetchJob).not.toHaveBeenCalled();
  });

  it("stops polling when aborted", async () => {
    const { chunks, writer } = recorder();
    const controller = new AbortController();
    const fetchJob = vi.fn().mockImplementation(async () => {
      controller.abort();
      return jobWith("running");
    });
    await streamJob({ writer, jobId: "j", fetchJob, signal: controller.signal, sleep: noSleep });
    expect(fetchJob).toHaveBeenCalledTimes(1);
    expect(chunks.some((chunk) => chunk.type === "finish")).toBe(false);
  });

  it("reports an error after repeated fetch failures", async () => {
    const { chunks, writer } = recorder();
    const fetchJob = vi.fn().mockRejectedValue(new BackendError("The build service is unreachable.", 503));
    await streamJob({ writer, jobId: "j", fetchJob, sleep: noSleep, maxConsecutiveErrors: 3 });
    expect(fetchJob).toHaveBeenCalledTimes(3);
    expect(chunks).toEqual([{ type: "error", errorText: "The build service is unreachable." }]);
  });

  it("reports a missing job immediately", async () => {
    const { chunks, writer } = recorder();
    const fetchJob = vi.fn().mockRejectedValue(new BackendError("Job not found.", 404));
    await streamJob({ writer, jobId: "j", fetchJob, sleep: noSleep });
    expect(fetchJob).toHaveBeenCalledTimes(1);
    expect(chunks).toEqual([{ type: "error", errorText: "Job not found." }]);
  });

  it("carries the parent job in metadata for follow-up builds", async () => {
    const { chunks, writer } = recorder();
    const job = jobWith("succeeded", (source) => {
      source.request.metadata = { based_on_job_id: "parent-1" };
    });
    await streamJob({ writer, jobId: job.job_id, fetchJob: async () => job, sleep: noSleep });
    expect(chunks[0]).toMatchObject({ messageMetadata: { basedOnJobId: "parent-1" } });
  });
});
