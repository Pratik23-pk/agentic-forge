import { describe, expect, it } from "vitest";

import type { BackendJob } from "@/lib/backend/types";
import type { ForgeDataParts, StageId, StageStatus } from "@/lib/contract";
import awaitingContract from "./__fixtures__/awaiting-product-contract.json";
import awaitingRelease from "./__fixtures__/awaiting-release.json";
import runningStart from "./__fixtures__/running-start.json";
import succeeded from "./__fixtures__/succeeded.json";
import {
  conversationFromJobs,
  isLive,
  jobToMessage,
  jobToParts,
  type ForgePart,
} from "./translate";

const clone = (job: unknown) => structuredClone(job) as BackendJob;

function stages(job: BackendJob): Partial<Record<StageId, StageStatus>> {
  return Object.fromEntries(
    jobToParts(job)
      .filter((part): part is ForgePart<"stage"> => part.type === "data-stage")
      .map((part) => [part.data.stage, part.data.status]),
  );
}

function partsOf<K extends keyof ForgeDataParts>(job: BackendJob, kind: K): ForgeDataParts[K][] {
  return jobToParts(job)
    .filter((part) => part.type === `data-${kind}`)
    .map((part) => part.data as ForgeDataParts[K]);
}

function building(): BackendJob {
  const job = clone(succeeded);
  job.status = "running";
  job.release_status = "pending";
  job.artifacts = [];
  job.evaluation = null;
  job.tasks[0].status = "succeeded";
  job.tasks[1].status = "pending";
  return job;
}

describe("isLive", () => {
  it("treats running, evaluating, retrying and pending as live", () => {
    for (const status of ["pending", "running", "evaluating", "retrying"]) {
      expect(isLive({ ...clone(succeeded), status })).toBe(true);
    }
  });

  it("treats review and terminal states as not live", () => {
    for (const status of ["awaiting_human_feedback", "succeeded", "failed", "blocked", "mystery"]) {
      expect(isLive({ ...clone(succeeded), status })).toBe(false);
    }
  });
});

describe("stages", () => {
  it("shows planning as running at the start of a job", () => {
    expect(stages(clone(runningStart))).toMatchObject({ plan: "running", design: "queued" });
  });

  it("puts plan in review while the product contract awaits approval", () => {
    const result = stages(clone(awaitingContract));
    expect(result.plan).toBe("review");
    expect(result.backend).toBe("queued");
    expect(result.frontend).toBe("queued");
  });

  it("marks the first pending worker as running while the job builds", () => {
    expect(stages(building())).toMatchObject({
      plan: "done",
      design: "done",
      backend: "done",
      frontend: "running",
      validate: "queued",
    });
  });

  it("only includes workers the plan created", () => {
    expect(stages(clone(succeeded)).database).toBeUndefined();
  });

  it("puts release in review while the release gate is pending", () => {
    const result = stages(clone(awaitingRelease));
    expect(result.release).toBe("review");
    expect(result.validate).toBe("done");
    expect(result.evaluate).toBe("done");
  });

  it("marks everything done for a verified success", () => {
    const result = stages(clone(succeeded));
    for (const status of Object.values(result)) expect(status).toBe("done");
  });

  it("carries the attempt number of a repairing worker", () => {
    const job = building();
    job.status = "retrying";
    job.tasks[1].status = "running";
    job.tasks[1].attempt = 2;
    const frontend = partsOf(job, "stage").find((stage) => stage.stage === "frontend");
    expect(frontend).toMatchObject({ status: "running", attempt: 2 });
  });

  it("fails the first unfinished stage when a job fails without a failed stage", () => {
    const job = building();
    job.status = "failed";
    job.errors = ["RuntimeError: model unavailable"];
    expect(stages(job)).toMatchObject({ frontend: "failed", validate: "queued" });
  });

  it("marks validation failed when the folder artifact failed validation", () => {
    const job = clone(succeeded);
    job.status = "failed";
    job.release_status = "provisional";
    job.evaluation = null;
    job.artifacts[0].metadata.validation = { passed: false, failure_reason: "Tests failed" };
    expect(stages(job).validate).toBe("failed");
  });

  it("fails release for quarantined builds", () => {
    const job = clone(succeeded);
    job.release_status = "quarantined";
    expect(stages(job).release).toBe("failed");
  });
});

describe("checkpoints", () => {
  it("emits the pending product contract with its visual", () => {
    const [checkpoint] = partsOf(clone(awaitingContract), "checkpoint");
    expect(checkpoint).toMatchObject({ gate: "product_contract", status: "pending" });
    expect(checkpoint.visual).toContain("Habit Tracker");
    expect(checkpoint.prompt).toMatch(/confirm the product scope/i);
  });

  it("keeps resolved checkpoints so history shows the decision", () => {
    const checkpoints = partsOf(clone(succeeded), "checkpoint");
    expect(checkpoints.map((checkpoint) => checkpoint.status)).toEqual(["approved", "approved"]);
  });
});

describe("files", () => {
  it("lists manifest files and skips deleted ones", () => {
    const job = clone(succeeded);
    const [first, second] = Object.keys(job.manifest_state!.files!);
    job.manifest_state!.files![second].deleted = true;
    job.manifest_state!.files![first].revision = 2;

    const files = partsOf(job, "file");
    expect(files).toHaveLength(Object.keys(job.manifest_state!.files!).length - 1);
    expect(files.find((file) => file.path === first)?.op).toBe("patch");
    expect(files.some((file) => file.path === second)).toBe(false);
  });

  it("measures bytes as UTF-8", () => {
    const job = clone(succeeded);
    const [first] = Object.keys(job.manifest_state!.files!);
    job.manifest_state!.files![first].content = "é";
    expect(partsOf(job, "file").find((file) => file.path === first)?.bytes).toBe(2);
  });
});

describe("validation", () => {
  it("maps command results with durations and stderr excerpts", () => {
    const job = clone(succeeded);
    job.validation_results = [
      {
        name: "frontend_tests",
        command: "npm test",
        passed: false,
        exit_code: 1,
        stdout_excerpt: "",
        stderr_excerpt: "FAIL src/App.test.tsx",
        duration_seconds: 4.2,
      },
    ];
    expect(partsOf(job, "validation")).toEqual([
      {
        name: "frontend_tests",
        command: "npm test",
        passed: false,
        durationMs: 4200,
        excerpt: "FAIL src/App.test.tsx",
      },
    ]);
  });
});

describe("job part", () => {
  it("reports release, cost and readiness", () => {
    const [job] = partsOf(clone(succeeded), "job");
    expect(job).toMatchObject({
      status: "succeeded",
      releaseStatus: "verified",
      usedFallback: false,
      artifactsReady: true,
      budgetUsd: 1,
    });
  });

  it("flags template fallback", () => {
    const source = clone(succeeded);
    source.worker_results[0].used_fallback = true;
    expect(partsOf(source, "job")[0].usedFallback).toBe(true);
  });

  it("surfaces the last error, then the evaluation failure", () => {
    const source = building();
    source.status = "failed";
    source.errors = ["first", "RuntimeError: last"];
    expect(partsOf(source, "job")[0].error).toBe("RuntimeError: last");

    source.errors = [];
    source.evaluation = { passed: false, failure_reason: "Missing delivery calendar" };
    expect(partsOf(source, "job")[0].error).toBe("Missing delivery calendar");
  });
});

describe("summary", () => {
  it("describes each phase of the job", () => {
    const text = (job: BackendJob) => partsOf(job, "summary")[0].text;
    expect(text(clone(runningStart))).toMatch(/planning/i);
    expect(text(clone(awaitingContract))).toMatch(/approve/i);
    expect(text(building())).toMatch(/building/i);
    expect(text(clone(succeeded))).toMatch(/verified/i);

    const failed = building();
    failed.status = "failed";
    failed.errors = ["RuntimeError: model unavailable"];
    expect(text(failed)).toMatch(/model unavailable/);
  });
});

describe("robustness", () => {
  it("never throws on unknown statuses or missing optional fields", () => {
    const job = clone(runningStart);
    job.status = "teleporting";
    job.release_status = "unknown";
    delete job.manifest_state;
    delete job.validation_results;
    delete job.cost_ledger;
    expect(() => jobToParts(job)).not.toThrow();
  });

  it("gives every part a unique, stable id", () => {
    const ids = jobToParts(clone(succeeded)).map((part) => part.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(jobToParts(clone(succeeded)).map((part) => part.id)).toEqual(ids);
  });
});

describe("messages", () => {
  it("builds an assistant message keyed by job id", () => {
    const job = clone(succeeded);
    const message = jobToMessage(job);
    expect(message).toMatchObject({
      id: `job-${job.job_id}`,
      role: "assistant",
      metadata: { jobId: job.job_id, projectId: job.request.project_id },
    });
    expect(message.parts.length).toBe(jobToParts(job).length);
  });

  it("builds a conversation from a job chain using the typed prompt", () => {
    const first = clone(succeeded);
    const second = clone(succeeded);
    second.job_id = "second";
    second.request.prompt = "Build a new version... (long composed prompt)";
    second.request.metadata = {
      display_prompt: "Add a streak counter",
      based_on_job_id: first.job_id,
    };

    const messages = conversationFromJobs([first, second]);
    expect(messages.map((message) => message.role)).toEqual(["user", "assistant", "user", "assistant"]);
    expect(messages[2].parts[0]).toEqual({ type: "text", text: "Add a streak counter" });
    expect(messages[3].metadata?.basedOnJobId).toBe(first.job_id);
  });
});
