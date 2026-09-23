export type JobStatus =
  | "pending"
  | "running"
  | "awaiting_human_feedback"
  | "evaluating"
  | "retrying"
  | "succeeded"
  | "failed"
  | "blocked";

export type ReleaseStatus = "pending" | "verified" | "provisional" | "quarantined";

export type TaskStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";

export type WorkerKind = "database" | "backend" | "frontend";

export type HumanFeedbackStatus =
  | "pending"
  | "approved"
  | "changes_requested"
  | "auto_approved";

export type HumanFeedbackDecision = "approve" | "request_changes";

export type ApprovalGate =
  | "product_contract"
  | "privileged_action"
  | "release"
  | "worker_review";

export interface JobTask {
  task_id: string;
  worker_kind: WorkerKind;
  title: string;
  instructions: string;
  status: TaskStatus;
  attempt: number;
  max_attempts: number;
  depends_on: string[];
  capability_id: string;
  adapter_ids: string[];
  transport_attempts: number;
  repair_rejections: number;
}

export interface GuardrailFinding {
  name: string;
  passed: boolean;
  severity: string;
  message: string;
  metadata: Record<string, unknown>;
}

export interface GuardrailReport {
  name: string;
  passed: boolean;
  findings: GuardrailFinding[];
}

export interface WorkerResult {
  task_id: string;
  worker_kind: WorkerKind;
  status: TaskStatus;
  summary: string;
  output: string;
  errors: string[];
  artifacts: string[];
  tool_calls: Array<{
    tool: string;
    status: string;
    input_summary: string;
    output_summary: string;
    metadata: Record<string, unknown>;
  }>;
  attempt: number;
  used_fallback: boolean;
}

export interface JobArtifact {
  artifact_id: string;
  kind: "folder" | "zip" | string;
  name: string;
  path: string;
  url: string;
  metadata: Record<string, unknown>;
}

export interface HumanFeedbackRequest {
  checkpoint_id: string;
  gate: ApprovalGate;
  worker_kind: WorkerKind | null;
  task_id: string | null;
  attempt: number;
  title: string;
  prompt: string;
  summary: string;
  visual_type: string;
  visual_content: string;
  status: HumanFeedbackStatus;
  response: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface JobState {
  job_id: string;
  status: JobStatus;
  request: {
    prompt: string;
    project_id: string;
    metadata: Record<string, unknown>;
  };
  project_spec: {
    capability_id: string;
    application_type: string;
    frontend_framework: string | null;
    backend_framework: string | null;
    primary_languages: string[];
    ports: Record<string, number>;
    adapter_ids: string[];
    acceptance_criteria: string[];
  };
  design_spec: Record<string, unknown>;
  approval_state: {
    revision?: number;
    gates?: Record<string, {
      revision: number;
      status: HumanFeedbackStatus;
      payload: Record<string, unknown>;
    }>;
  };
  cost_ledger: {
    currency?: string;
    normal_limit_usd?: number;
    hard_limit_usd?: number;
    spent_usd?: number;
    prompt_tokens?: number;
    cached_prompt_tokens?: number;
    completion_tokens?: number;
    reasoning_tokens?: number;
    calls?: Array<Record<string, unknown>>;
    authorizations?: Record<string, number>;
  };
  tasks: JobTask[];
  worker_results: WorkerResult[];
  guardrail_reports: GuardrailReport[];
  artifacts: JobArtifact[];
  release_status: ReleaseStatus;
  risk_findings: Array<{
    source: string;
    name: string;
    severity: string;
    message: string;
    blocking: boolean;
    metadata?: Record<string, unknown>;
  }>;
  artifact_errors: string[];
  validation_results: Array<{
    name: string;
    command: string;
    passed: boolean;
    exit_code: number | null;
    stdout_excerpt: string;
    stderr_excerpt: string;
    phase?: string;
    failure_kind?: "application" | "security" | "infrastructure" | null;
    blocking?: boolean;
    timed_out?: boolean;
    attempt?: number;
  }>;
  repair_tickets: Array<{
    ticket_id: string;
    source: string;
    worker_kind: WorkerKind;
    category: string;
    summary: string;
    fingerprint: string;
    occurrence: number;
    strategy: "targeted_patch" | "escalated_patch" | "certified_recovery" | string;
    target_files: string[];
    resolved: boolean;
  }>;
  failure_fingerprints: Record<string, number>;
  feedback_requests: HumanFeedbackRequest[];
  active_feedback_request_id: string | null;
  evaluation: {
    passed: boolean;
    retry_targets: WorkerKind[];
    replan_required: boolean;
    failure_reason: string | null;
    checks: string[];
    context_pruned: boolean;
    decision: "approved" | "repair_required" | "warning" | string;
    warnings: string[];
    evidence: Array<Record<string, unknown>>;
  } | null;
  loop_count: number;
  errors: string[];
  warnings: string[];
  created_at: string;
  updated_at: string;
  route?: {
    action: string;
    reason: string;
    retry_targets: WorkerKind[];
  };
}

export interface Metrics {
  jobs_submitted: number;
  jobs_succeeded: number;
  jobs_failed: number;
  retries_scheduled: number;
  guardrail_blocks: number;
  human_checkpoints_created: number;
  human_feedback_approved: number;
  human_feedback_changes_requested: number;
  mcp_tool_calls: number;
  started_at: number;
}

export interface GeneratedFile {
  path: string;
  size: number;
}

export interface GeneratedFileList {
  root: string;
  files: GeneratedFile[];
}

export interface FileUpdateResult {
  path: string;
  size: number;
  sha256: string;
  revision: {
    revision_id: string;
    path: string;
    sha256: string;
    created_at: number;
  } | null;
}

export interface PreviewService {
  name: string;
  component: string;
  port: number;
  url: string;
  status: string;
  pid: number | null;
  log_path: string;
}

export interface PreviewRecord {
  job_id: string;
  status: "starting" | "running" | "stopped" | "failed";
  services: PreviewService[];
  started_at: number;
  stopped_at: number | null;
  error: string | null;
  sandbox_mode: "local" | "docker";
  release_status: ReleaseStatus;
  quarantined: boolean;
  checks: Array<{ name: string; passed: boolean; message: string }>;
  screenshot_path: string | null;
}

export interface DesignTokenFile {
  path: string;
  sha256: string;
  tokens: Record<string, string>;
}

export interface ProviderStatus {
  provider: "github" | "supabase";
  configured: boolean;
  enabled: boolean;
  capabilities: string[];
  documentation_url: string;
}

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    },
    ...init
  });

  if (!response.ok) {
    const errorText = await response.text();
    if (response.status === 502 || response.status === 503) {
      throw new Error(
        "The Agentic Forge backend is unavailable. Start it with ./scripts/run_backend.sh, then retry."
      );
    }
    throw new Error(errorText || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function submitJob(
  prompt: string,
  projectId: string,
  runImmediately: boolean,
  capabilityId?: string
): Promise<JobState> {
  return request<JobState>("/api/jobs", {
    method: "POST",
    body: JSON.stringify({
      prompt,
      project_id: projectId,
      run_immediately: runImmediately,
      metadata: capabilityId ? { capability_id: capabilityId } : {}
    })
  });
}

export function runNextJob(): Promise<JobState | { status: "idle" }> {
  return request<JobState | { status: "idle" }>("/api/jobs/work-next", {
    method: "POST"
  });
}

export function submitHumanFeedback(
  jobId: string,
  decision: HumanFeedbackDecision,
  message?: string
): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ decision, message })
  });
}

export function listJobs(): Promise<JobState[]> {
  return request<JobState[]>("/api/jobs");
}

export function getJob(jobId: string): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}`);
}

export function listGeneratedFiles(jobId: string): Promise<GeneratedFileList> {
  return request<GeneratedFileList>(`/api/jobs/${jobId}/files`);
}

export async function getGeneratedFileContent(jobId: string, path: string): Promise<string> {
  const response = await fetch(
    `${apiBase}/api/jobs/${jobId}/files/content?path=${encodeURIComponent(path)}`
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Request failed with ${response.status}`);
  }
  return response.text();
}

export function updateGeneratedFile(
  jobId: string,
  path: string,
  content: string,
  expectedSha256: string
): Promise<FileUpdateResult> {
  return request<FileUpdateResult>(
    `/api/jobs/${jobId}/files/content?path=${encodeURIComponent(path)}`,
    {
      method: "PUT",
      body: JSON.stringify({ content, expected_sha256: expectedSha256 })
    }
  );
}

export function startPreview(jobId: string): Promise<PreviewRecord> {
  return request<PreviewRecord>(`/api/jobs/${jobId}/preview`, { method: "POST" });
}

export function getPreview(jobId: string): Promise<PreviewRecord> {
  return request<PreviewRecord>(`/api/jobs/${jobId}/preview`);
}

export function stopPreview(jobId: string): Promise<PreviewRecord> {
  return request<PreviewRecord>(`/api/jobs/${jobId}/preview`, { method: "DELETE" });
}

export async function getPreviewLogs(jobId: string): Promise<string> {
  const response = await fetch(`${apiBase}/api/jobs/${jobId}/preview/logs`);
  if (!response.ok) {
    throw new Error((await response.text()) || `Request failed with ${response.status}`);
  }
  return response.text();
}

export function previewScreenshotUrl(jobId: string): string {
  return `${apiBase}/api/jobs/${jobId}/preview/screenshot`;
}

export function collaborationWebSocketUrl(jobId: string): string {
  const base = apiBase ? new URL(apiBase, window.location.href) : new URL(window.location.href);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = `/api/jobs/${jobId}/collaboration`;
  base.search = "";
  base.hash = "";
  return base.toString();
}

export function listDesignTokens(jobId: string): Promise<{ files: DesignTokenFile[] }> {
  return request<{ files: DesignTokenFile[] }>(`/api/jobs/${jobId}/design-tokens`);
}

export function updateDesignTokens(
  jobId: string,
  path: string,
  tokens: Record<string, string>,
  expectedSha256: string
): Promise<DesignTokenFile> {
  return request<DesignTokenFile>(`/api/jobs/${jobId}/design-tokens`, {
    method: "PUT",
    body: JSON.stringify({ path, tokens, expected_sha256: expectedSha256 })
  });
}

export function listProviderStatus(): Promise<ProviderStatus[]> {
  return request<ProviderStatus[]>("/api/providers");
}

export function syncToGitHub(
  jobId: string,
  payload: {
    owner: string;
    repository: string;
    branch: string;
    create_pull_request: boolean;
  }
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/providers/jobs/${jobId}/github/sync`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createSupabaseProject(payload: {
  name: string;
  organization_slug: string;
  database_password: string;
  confirm_billing: boolean;
}): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/api/providers/supabase/projects", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function generatedProjectDownloadUrl(jobId: string): string {
  return `${apiBase}/api/jobs/${jobId}/download`;
}

export function getMetrics(): Promise<Metrics> {
  return request<Metrics>("/api/metrics");
}
