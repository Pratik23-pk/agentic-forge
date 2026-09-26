/**
 * Draft event contract between the Studio gateway and the UI.
 *
 * Each build streams as an AI SDK UI message. Progress travels as custom
 * `data-*` parts; parts that share an `id` (e.g. `stage-backend`,
 * `file-src/App.tsx`) are reconciled in place by `useChat`, so the UI
 * always renders current state rather than a log of updates.
 *
 * Phase 2 fills these from the existing job API; later the Python backend
 * emits them directly. See docs/frontend/roadmap.md.
 */
import type { UIMessage } from "ai";

export type StageId =
  | "plan"
  | "design"
  | "database"
  | "backend"
  | "frontend"
  | "validate"
  | "evaluate"
  | "release";

export type StageStatus = "queued" | "running" | "review" | "done" | "failed";

export type WorkerKind = "database" | "backend" | "frontend";

export type ReleaseStatus = "pending" | "verified" | "provisional" | "quarantined";

export type ForgeDataParts = {
  stage: {
    stage: StageId;
    status: StageStatus;
    attempt?: number;
    detail?: string;
  };
  file: {
    path: string;
    worker: WorkerKind;
    bytes: number;
    op: "create" | "patch";
  };
  validation: {
    name: string;
    command: string;
    passed: boolean;
    durationMs?: number;
    excerpt?: string;
  };
  checkpoint: {
    checkpointId: string;
    gate: "product_contract" | "privileged_action" | "release" | "worker_review" | (string & {});
    status: "pending" | "approved" | "changes_requested" | "auto_approved" | (string & {});
    title: string;
    prompt: string;
    summary: string;
    /** Pretty-printed JSON or plain text the reviewer is approving. */
    visual?: string;
    response?: string;
  };
  /** One per job: outcome, cost and whether a template stood in for model output. */
  job: {
    status: string;
    releaseStatus: ReleaseStatus | (string & {});
    costUsd: number;
    budgetUsd: number;
    usedFallback: boolean;
    artifactsReady: boolean;
    error?: string;
  };
  /** Markdown summary. A data part (not text) so re-attaching never duplicates it. */
  summary: {
    text: string;
  };
};

export type ForgeMessageMetadata = {
  jobId: string;
  projectId: string;
  basedOnJobId?: string;
};

export type ForgeMessage = UIMessage<ForgeMessageMetadata, ForgeDataParts>;

export type StagePart = ForgeDataParts["stage"];
export type FilePart = ForgeDataParts["file"];
export type ValidationPart = ForgeDataParts["validation"];
export type CheckpointPart = ForgeDataParts["checkpoint"];
export type JobPart = ForgeDataParts["job"];
export type SummaryPart = ForgeDataParts["summary"];

export const STAGE_LABELS: Record<StageId, string> = {
  plan: "Plan",
  design: "Design direction",
  database: "Database",
  backend: "Backend",
  frontend: "Frontend",
  validate: "Validate",
  evaluate: "Evaluate",
  release: "Release",
};
