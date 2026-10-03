/**
 * The subset of the Python API's job JSON the studio reads. Hand-typed from
 * backend/src/software_developer_agent/models/job_state.py because the API has
 * no response models yet (roadmap ask #1). Fields are optional where older or
 * partial jobs may omit them; readers must tolerate unknown string values.
 */

export type BackendJobStatus =
  | "pending"
  | "running"
  | "awaiting_human_feedback"
  | "evaluating"
  | "retrying"
  | "succeeded"
  | "failed"
  | "blocked";

export type BackendWorkerKind = "database" | "backend" | "frontend";

export interface BackendTask {
  task_id: string;
  worker_kind: BackendWorkerKind;
  title: string;
  status: string;
  attempt: number;
  max_attempts: number;
}

export interface BackendWorkerResult {
  task_id: string;
  worker_kind: BackendWorkerKind;
  status: string;
  summary: string;
  attempt: number;
  used_fallback: boolean;
}

export interface BackendManifestFile {
  path: string;
  content: string;
  worker_kind: BackendWorkerKind;
  revision: number;
  deleted: boolean;
}

export interface BackendValidationResult {
  name: string;
  command: string;
  passed: boolean;
  exit_code: number | null;
  stdout_excerpt: string;
  stderr_excerpt: string;
  phase?: string;
  failure_kind?: string | null;
  blocking?: boolean;
  timed_out?: boolean;
  attempt?: number;
  duration_seconds?: number;
}

export interface BackendArtifact {
  artifact_id: string;
  kind: string;
  name: string;
  path: string;
  url: string;
  metadata: {
    file_count?: number;
    release_status?: string;
    publish_allowed?: boolean;
    validation?: {
      passed?: boolean;
      failure_reason?: string | null;
      checks?: string[];
    };
    [key: string]: unknown;
  };
}

export interface BackendFeedbackRequest {
  checkpoint_id: string;
  gate: string;
  worker_kind: BackendWorkerKind | null;
  attempt: number;
  title: string;
  prompt: string;
  summary: string;
  visual_type: string;
  visual_content: string;
  status: string;
  response: string | null;
  created_at: string;
}

export interface BackendGuardrailFinding {
  name: string;
  passed: boolean;
  severity: string;
  message: string;
  metadata: Record<string, unknown>;
}

export interface BackendGuardrailReport {
  name: string;
  passed: boolean;
  findings: BackendGuardrailFinding[];
}

export interface BackendJob {
  job_id: string;
  status: string;
  release_status: string;
  request: {
    prompt: string;
    project_id: string;
    metadata: Record<string, unknown>;
  };
  project_spec?: {
    capability_id?: string;
    frontend_framework?: string | null;
    backend_framework?: string | null;
    acceptance_criteria?: string[];
  };
  design_spec?: {
    product_summary?: string;
    [key: string]: unknown;
  };
  cost_ledger?: {
    spent_usd?: number;
    hard_limit_usd?: number;
    normal_limit_usd?: number;
  };
  tasks: BackendTask[];
  worker_results: BackendWorkerResult[];
  manifest_state?: { files?: Record<string, BackendManifestFile> };
  guardrail_reports?: BackendGuardrailReport[];
  artifacts: BackendArtifact[];
  artifact_errors?: string[];
  validation_results?: BackendValidationResult[];
  feedback_requests: BackendFeedbackRequest[];
  active_feedback_request_id: string | null;
  evaluation: {
    passed: boolean;
    decision?: string;
    failure_reason: string | null;
    warnings?: string[];
  } | null;
  errors: string[];
  warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface BackendFileListing {
  root: string;
  files: Array<{ path: string; size: number }>;
}

export interface BackendPreviewService {
  name: string;
  component: string;
  port: number;
  url: string;
  status: string;
}

export interface BackendPreview {
  job_id: string;
  status: "starting" | "running" | "stopped" | "failed" | string;
  services: BackendPreviewService[];
  error: string | null;
  sandbox_mode: string;
  release_status: string;
  quarantined: boolean;
  checks: Array<{ name: string; passed: boolean; message: string }>;
  screenshot_path: string | null;
}

export interface BackendProviderStatus {
  provider: "github" | "supabase" | string;
  configured: boolean;
  enabled: boolean;
  capabilities: string[];
  documentation_url: string;
}
