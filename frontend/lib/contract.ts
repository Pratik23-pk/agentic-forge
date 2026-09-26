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
    gate: "product_contract" | "privileged_action" | "release" | "worker_review";
    title: string;
    summary: string;
    visual?: string;
  };
  preview: {
    status: "starting" | "running" | "stopped" | "failed";
    url?: string;
    error?: string;
  };
  release: {
    status: ReleaseStatus;
    /** True when a worker fell back to a template instead of model output. */
    usedFallback: boolean;
    costUsd: number;
  };
  /** Sent transient: surfaced as a toast, never stored in message history. */
  notice: {
    level: "info" | "warn";
    text: string;
  };
};

export type ForgeMessageMetadata = {
  jobId: string;
  projectId: string;
};

export type ForgeMessage = UIMessage<ForgeMessageMetadata, ForgeDataParts>;

export type StagePart = ForgeDataParts["stage"];
export type FilePart = ForgeDataParts["file"];
export type ValidationPart = ForgeDataParts["validation"];
export type CheckpointPart = ForgeDataParts["checkpoint"];
export type ReleasePart = ForgeDataParts["release"];

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
