create extension if not exists vector;

create table if not exists agent_jobs (
  job_id text primary key,
  project_id text not null,
  prompt text not null,
  status text not null,
  loop_count integer not null default 0,
  snapshot jsonb not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create index if not exists idx_agent_jobs_project_updated
  on agent_jobs (project_id, updated_at desc);

create index if not exists idx_agent_jobs_status
  on agent_jobs (status);

create table if not exists agent_tasks (
  task_id text primary key,
  job_id text not null references agent_jobs(job_id) on delete cascade,
  worker_kind text not null,
  title text not null,
  status text not null,
  attempt integer not null default 0,
  max_attempts integer not null default 2,
  instructions text not null,
  depends_on text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists agent_worker_results (
  result_id bigserial primary key,
  job_id text not null references agent_jobs(job_id) on delete cascade,
  task_id text not null,
  worker_kind text not null,
  status text not null,
  summary text not null,
  output text not null default '',
  errors jsonb not null default '[]',
  artifacts jsonb not null default '[]',
  tool_calls jsonb not null default '[]',
  attempt integer not null default 1,
  created_at timestamptz not null default now()
);

create table if not exists agent_guardrail_reports (
  report_id bigserial primary key,
  job_id text not null references agent_jobs(job_id) on delete cascade,
  name text not null,
  passed boolean not null,
  findings jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table if not exists agent_evaluations (
  evaluation_id bigserial primary key,
  job_id text not null references agent_jobs(job_id) on delete cascade,
  passed boolean not null,
  retry_targets text[] not null default '{}',
  failure_reason text,
  checks text[] not null default '{}',
  context_pruned boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists agent_tool_calls (
  tool_call_id bigserial primary key,
  job_id text not null references agent_jobs(job_id) on delete cascade,
  task_id text,
  tool_name text not null,
  status text not null,
  input_summary text not null default '',
  output_summary text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists agent_artifacts (
  artifact_id text not null,
  job_id text not null references agent_jobs(job_id) on delete cascade,
  kind text not null,
  name text not null,
  path text not null,
  url text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  primary key (job_id, artifact_id)
);

create table if not exists project_memory (
  memory_id bigserial primary key,
  project_id text not null,
  kind text not null,
  content text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists project_memory_embeddings (
  memory_id bigint primary key references project_memory(memory_id) on delete cascade,
  embedding vector(1536) not null
);

create index if not exists idx_project_memory_project_kind
  on project_memory (project_id, kind, created_at desc);
