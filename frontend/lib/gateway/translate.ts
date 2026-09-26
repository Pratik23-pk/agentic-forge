/**
 * Translates the Python API's job JSON into the studio's streaming contract.
 * Pure and total: any job, including partial or unknown states, produces a
 * renderable set of parts. Each part has a stable id so the same job always
 * yields the same ids, which is what makes re-attaching to a stream safe.
 */
import type { BackendJob, BackendTask } from "@/lib/backend/types";
import type { ForgeDataParts, ForgeMessage, StagePart, StageStatus } from "@/lib/contract";

export type ForgePart<K extends keyof ForgeDataParts = keyof ForgeDataParts> = {
  [Name in K]: { type: `data-${Name}`; id: string; data: ForgeDataParts[Name] };
}[K];

const LIVE_STATUSES = new Set(["pending", "running", "evaluating", "retrying"]);
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "blocked"]);
const WORKER_ORDER = ["database", "backend", "frontend"] as const;

export function isLive(job: Pick<BackendJob, "status">): boolean {
  return LIVE_STATUSES.has(job.status);
}

function activeGate(job: BackendJob): string | undefined {
  return job.feedback_requests.find(
    (request) =>
      request.checkpoint_id === job.active_feedback_request_id && request.status === "pending",
  )?.gate;
}

function folderArtifact(job: BackendJob) {
  return job.artifacts.find((artifact) => artifact.kind === "folder");
}

function orderedTasks(job: BackendJob): BackendTask[] {
  return [...job.tasks].sort(
    (a, b) => WORKER_ORDER.indexOf(a.worker_kind) - WORKER_ORDER.indexOf(b.worker_kind),
  );
}

function deriveStages(job: BackendJob): StagePart[] {
  const live = isLive(job);
  const gate = activeGate(job);
  const tasks = orderedTasks(job);
  const folder = folderArtifact(job);
  const stages: StagePart[] = [];

  const planDone = tasks.length > 0 && gate !== "product_contract";
  stages.push({
    stage: "plan",
    status: gate === "product_contract" ? "review" : planDone ? "done" : live ? "running" : "queued",
  });

  const designed = Boolean(job.design_spec?.product_summary);
  stages.push({
    stage: "design",
    status: designed ? "done" : planDone && live ? "running" : "queued",
  });

  const anyRunning = tasks.some((task) => task.status === "running");
  let earlierAllDone = true;
  for (const task of tasks) {
    let status: StageStatus;
    if (task.status === "succeeded") status = "done";
    else if (task.status === "failed") status = "failed";
    else if (task.status === "running") status = "running";
    else if (live && !gate && !anyRunning && earlierAllDone && planDone) status = "running";
    else status = "queued";
    if (task.status !== "succeeded") earlierAllDone = false;
    stages.push({
      stage: task.worker_kind,
      status,
      ...(task.attempt > 1 ? { attempt: task.attempt } : {}),
    });
  }

  const allTasksDone = tasks.length > 0 && tasks.every((task) => task.status === "succeeded");
  const validationPassed = folder?.metadata.validation?.passed;
  stages.push({
    stage: "validate",
    status: folder
      ? validationPassed === false
        ? "failed"
        : "done"
      : allTasksDone && live
        ? "running"
        : "queued",
    ...(folder?.metadata.validation?.failure_reason
      ? { detail: folder.metadata.validation.failure_reason }
      : {}),
  });

  stages.push({
    stage: "evaluate",
    status:
      job.status === "evaluating"
        ? "running"
        : job.evaluation?.passed
          ? "done"
          : job.evaluation
            ? "failed"
            : "queued",
  });

  const terminal = TERMINAL_STATUSES.has(job.status);
  let release: StageStatus = "queued";
  if (gate === "release") release = "review";
  else if (job.release_status === "quarantined") release = "failed";
  else if (job.status === "succeeded") release = "done";
  else if (terminal && folder) release = "failed";
  stages.push({ stage: "release", status: release });

  if ((job.status === "failed" || job.status === "blocked") && !stages.some((s) => s.status === "failed")) {
    const firstUnfinished = stages.find((s) => s.status === "queued" || s.status === "running");
    if (firstUnfinished) firstUnfinished.status = "failed";
  }

  return stages;
}

function lastError(job: BackendJob): string | undefined {
  const error = job.errors.at(-1);
  if (error) return error;
  if (job.evaluation && !job.evaluation.passed && job.evaluation.failure_reason) {
    return job.evaluation.failure_reason;
  }
  return job.artifact_errors?.at(-1);
}

function stackLabel(job: BackendJob): string | undefined {
  const parts = [job.project_spec?.frontend_framework, job.project_spec?.backend_framework].filter(
    (part): part is string => Boolean(part),
  );
  return parts.length ? parts.join(" + ") : undefined;
}

function fileCount(job: BackendJob): number {
  return Object.values(job.manifest_state?.files ?? {}).filter((file) => !file.deleted).length;
}

function summarize(job: BackendJob): string {
  const project = job.request.project_id;
  const stack = stackLabel(job);
  const files = fileCount(job);
  const gate = activeGate(job);
  const usedFallback = job.worker_results.some((result) => result.used_fallback);
  const fallbackNote = usedFallback
    ? "\n\nPart of this project came from a starter template because the model output could not be used."
    : "";

  if (job.status === "failed" || job.status === "blocked") {
    const error = lastError(job);
    const kept = job.artifacts.length
      ? " The latest files are still available to preview and download."
      : "";
    return `The build stopped${error ? `: ${error}` : "."}${kept}${fallbackNote}`;
  }

  if (job.status === "awaiting_human_feedback") {
    if (gate === "product_contract") {
      return `Planning is done for **${project}**${stack ? ` (${stack})` : ""}. Review the product contract below and approve it to start building.`;
    }
    if (gate === "release") {
      return `The build finished validation. Approve the release to finish.${fallbackNote}`;
    }
    if (gate === "privileged_action") {
      return "The build needs permission for an action outside the sandbox. Review the request below.";
    }
    return "The build is waiting for your review.";
  }

  if (job.status === "succeeded") {
    const what = `${files} files${stack ? `, ${stack}` : ""}`;
    if (job.release_status === "quarantined") {
      return `Built **${project}** (${what}), but security checks found blocking issues. Preview runs isolated and publishing is locked; the ZIP is still available.${fallbackNote}`;
    }
    if (job.release_status === "provisional") {
      return `Built **${project}** (${what}) with validation warnings. You can preview and download it.${fallbackNote}`;
    }
    return `Built and verified **${project}** (${what}). Preview it on the right, inspect the code, or download the ZIP.${fallbackNote}`;
  }

  if (job.status === "evaluating") {
    return "Checking the result against your request.";
  }

  if (job.status === "retrying") {
    const repairing = job.tasks.find((task) => task.status === "running" || task.status === "pending");
    return `Found an issue and repairing the ${repairing?.worker_kind ?? "affected"} code.`;
  }

  if (job.tasks.length === 0) {
    return `Planning **${project}** and choosing a stack.`;
  }

  return `Building **${project}**${stack ? ` with ${stack}` : ""}. ${files} ${files === 1 ? "file" : "files"} written so far.`;
}

const encoder = new TextEncoder();

export function jobToParts(job: BackendJob): ForgePart[] {
  const parts: ForgePart[] = [];

  parts.push({ type: "data-summary", id: "summary", data: { text: summarize(job) } });

  for (const stage of deriveStages(job)) {
    parts.push({ type: "data-stage", id: `stage-${stage.stage}`, data: stage });
  }

  for (const request of job.feedback_requests) {
    parts.push({
      type: "data-checkpoint",
      id: `checkpoint-${request.checkpoint_id}`,
      data: {
        checkpointId: request.checkpoint_id,
        gate: request.gate,
        status: request.status,
        title: request.title,
        prompt: request.prompt,
        summary: request.summary,
        ...(request.visual_content ? { visual: request.visual_content } : {}),
        ...(request.response ? { response: request.response } : {}),
      },
    });
  }

  const files = Object.values(job.manifest_state?.files ?? {})
    .filter((file) => !file.deleted)
    .sort((a, b) => a.path.localeCompare(b.path));
  for (const file of files) {
    parts.push({
      type: "data-file",
      id: `file-${file.path}`,
      data: {
        path: file.path,
        worker: file.worker_kind,
        bytes: encoder.encode(file.content ?? "").length,
        op: file.revision > 1 ? "patch" : "create",
      },
    });
  }

  // Repeated attempts report the same check again; the latest result wins.
  const latestValidation = new Map<string, NonNullable<BackendJob["validation_results"]>[number]>();
  for (const result of job.validation_results ?? []) latestValidation.set(result.name, result);
  for (const result of latestValidation.values()) {
    const excerpt = result.passed ? undefined : result.stderr_excerpt || result.stdout_excerpt;
    parts.push({
      type: "data-validation",
      id: `validation-${result.name}`,
      data: {
        name: result.name,
        command: result.command,
        passed: result.passed,
        ...(result.duration_seconds !== undefined
          ? { durationMs: Math.round(result.duration_seconds * 1000) }
          : {}),
        ...(excerpt ? { excerpt } : {}),
      },
    });
  }

  const error = TERMINAL_STATUSES.has(job.status) ? lastError(job) : undefined;
  parts.push({
    type: "data-job",
    id: "job",
    data: {
      status: job.status,
      releaseStatus: job.release_status,
      costUsd: job.cost_ledger?.spent_usd ?? 0,
      budgetUsd: job.cost_ledger?.hard_limit_usd ?? 1,
      usedFallback: job.worker_results.some((result) => result.used_fallback),
      artifactsReady:
        job.artifacts.some((artifact) => artifact.kind === "folder") &&
        job.artifacts.some((artifact) => artifact.kind === "zip"),
      ...(error ? { error } : {}),
    },
  });

  return parts;
}

function metadataString(job: BackendJob, key: string): string | undefined {
  const value = job.request.metadata?.[key];
  return typeof value === "string" && value ? value : undefined;
}

export function jobToMessage(job: BackendJob): ForgeMessage {
  const basedOnJobId = metadataString(job, "based_on_job_id");
  return {
    id: `job-${job.job_id}`,
    role: "assistant",
    metadata: {
      jobId: job.job_id,
      projectId: job.request.project_id,
      ...(basedOnJobId ? { basedOnJobId } : {}),
    },
    parts: jobToParts(job) as ForgeMessage["parts"],
  };
}

/** A user message and an assistant message per job, oldest first. */
export function conversationFromJobs(chain: BackendJob[]): ForgeMessage[] {
  return chain.flatMap((job) => [
    {
      id: `user-${job.job_id}`,
      role: "user" as const,
      parts: [{ type: "text" as const, text: metadataString(job, "display_prompt") ?? job.request.prompt }],
    },
    jobToMessage(job),
  ]);
}

