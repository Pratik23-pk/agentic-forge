# Operations

## Development

- Backend: `uvicorn software_developer_agent.main:app --reload`
- Frontend: `npm run dev`
- API docs: `http://localhost:8000/docs` in non-production environments

## Project Names

- Studio exposes a required project-name field and generates a new readable suggestion for every build.
- Blank and legacy placeholder names such as `default` and `build-27a` are replaced server-side with a prompt-derived name plus a collision-resistant suffix.
- Reusing an explicit project name intentionally reuses that project’s long-term planning memory.

## Human Checkpoints

- Enable or disable approval pauses with `ENABLE_HUMAN_CHECKPOINTS`.
- Cap user interruptions with `MAX_HUMAN_CHECKPOINTS`; the default is 4.
- Feedback approvals resume the next pending worker.
- Requested changes reset only the worker tied to the active checkpoint.
- Approval-only resumes do not increment the worker execution-loop counter.
- Automated packaging repairs do not repeatedly ask for visual approval.

## LangGraph Persistence

- Keep `ENABLE_LANGGRAPH_CHECKPOINTING=true` so retry manifests use deterministic state reducers.
- With `ENABLE_PERSISTENCE=true`, backend startup runs idempotent Postgres checkpoint and Store setup.
- `LANGGRAPH_STRICT_MSGPACK=true` restricts checkpoint deserialization to safe built-in data shapes.
- Supabase/Postgres stores thread checkpoints, canonical file manifests, and project-level decisions and constraints.
- Job snapshots retain a redundant canonical manifest so state can be reseeded if a development in-memory checkpointer restarts.

## MCP Tools

- Keep `ENABLE_MCP_TOOLS=true` to route agent tools through the MCP client/server boundary.
- Network tools still require their own flags, such as `ENABLE_WEB_SEARCH` and `ENABLE_BROWSER`.
- MCP calls are permission-checked by worker kind, timed, redacted, and attached to job history.

## Production Readiness Tasks

- Add identity, tenant isolation, and permission scopes for all job, artifact, preview, workspace, collaboration, and provider routes.
- Harden MCP deployment with process isolation before enabling shell, file-write, or deployment tools.
- Enable Redis-backed queueing with `ENABLE_REDIS=true` for multi-process workers.
- Enable Supabase/Postgres persistence with `ENABLE_PERSISTENCE=true`.
- Enable LangSmith tracing with `LANGSMITH_TRACING=true` for workflow observability.
- Add deployment-specific CI/CD secrets once the target host is selected.

## Preview Runtime

- Use `PREVIEW_SANDBOX_MODE=local` only for trusted localhost development.
- Production rejects local preview startup; set `PREVIEW_SANDBOX_MODE=docker` and keep Docker
  patched and isolated from the host Docker socket.
- Preview service URLs are local runtime addresses only. Public URL allocation, custom domains,
  subdomains, promotion, and production deployment are not implemented in the current release.
- Preview processes receive only a small environment allowlist; Agentic Forge API keys and provider
  credentials are never inherited.
- Stop previews from the studio or with `DELETE /api/jobs/{job_id}/preview`.
- Inspect service URLs with `GET /api/jobs/{job_id}/preview` and bounded logs with
  `GET /api/jobs/{job_id}/preview/logs`.

## Workspace

- File writes require the SHA-256 observed when the file was opened. Stale writes return HTTP 409.
- Previous content is retained under `.agentic-forge/previews/{job_id}/revisions/` and excluded
  from generated ZIPs.
- Lockfiles and generated blueprint metadata are read-only in the browser editor.
- CSS token writes may modify existing custom-property values only.
- WebSocket collaboration carries presence, cursor, selection, active-file, and file-update events;
  add authenticated tenant checks before public deployment.

## Providers

- Provider actions stay locked unless `ENABLE_PROVIDER_ACTIONS=true`.
- GitHub requires a token with repository Contents write permission; workflow files additionally
  require Workflows write permission. Sync uses Git blobs, trees, commits, refs, and optional PRs.
- Supabase Management API provisioning requires an access token and per-request
  `confirm_billing=true`. Agentic Forge does not persist the submitted database password.
- Supabase API-key metadata, storage buckets, and secret names are readable through guarded
  provider routes. Secret values are accepted only by the bulk-write route with
  `confirm_write=true` and are never included in Agentic Forge responses.

## Benchmarks

Offline structural benchmark:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  -m software_developer_agent.benchmarks.runner --repeat 2
```

Execution-grade benchmark:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  -m software_developer_agent.benchmarks.runner --execute --repeat 1
```

The execution run installs third-party packages and can take several minutes. Run it in CI on a
network-enabled isolated worker.

## Supabase

1. Create a Supabase project.
2. Enable the `vector` extension if it is not already enabled.
3. Run `backend/migrations/001_initial_supabase.sql`.
4. Put the pooled Postgres connection string in `DATABASE_URL`.
5. Start the backend once to initialize LangGraph checkpoint and Store tables.

## Redis

For local development, use the `redis` service in `docker-compose.yml`.
For managed production Redis, use Upstash first. Move to AWS ElastiCache only when VPC-local networking or heavier queue throughput is needed.

## Generated Artifacts

Workers must produce structured file manifests inside their owned component paths. The artifact
writer assembles them in staging, creates the npm lockfile, runs structural and executable
validation, verifies ZIP parity, and publishes atomically only after every gate passes. Tests/builds
and dependency audits are separate validation phases. Audit infrastructure failures never request a
code repair: the executable project remains previewable and downloadable as a provisional release,
while publication remains locked until security validation completes.

Successful workflows expose:

- A folder under `generated-projects/`.
- A ZIP package under `artifacts/`.
- File previews and a ZIP download link in the frontend runtime console.
- Validation commands, exit codes, durations, and output excerpts in job state and artifact metadata.

Failed workflows retain validation evidence. When an executable checkpoint exists, the runtime
restores it for isolated preview and ZIP download instead of discarding it; publication remains
locked until the blocking issue is resolved.
