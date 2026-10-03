# Agentic Forge — Architecture, Limitations and Fix Plan

A point-by-point review of the backend and platform. Each item says what is wrong, where, why it
matters and how to fix it. Ordered by severity, then by how much it blocks everything else.
File paths are relative to `backend/src/software_developer_agent/` unless shown otherwise.

---

## 1. How the system works today

```
Browser (Next.js studio)
   │  /api/chat (stream)          /api/jobs/* (REST, proxied)
   ▼                              ▼
Next.js gateway ──polls──► FastAPI (one process, no auth)
                              │  POST /api/jobs → BackgroundTasks (same process)
                              ▼
                     LangGraph workflow:
                     guardrails → plan → design → [approval]
                     → workers one after another (database → backend → frontend),
                       each one OpenAI call returning all its files as one JSON blob
                     → output scans → write files + ZIP
                     → validate (npm/pytest/build in fresh Docker containers)
                     → evaluator → router → repair loop (≤ 4 attempts) → [approval] → done
                              │
                              ▼
            generated-projects/<name>/  +  artifacts/<name>.zip
            Preview: Docker container behind nginx on 127.0.0.1:<port>
```

- Stack is chosen by keyword matching before any model call (`capabilities/registry.py:282`).
- State lives in memory by default; Supabase/Postgres and Redis are optional flags.
- Models: OpenAI Responses API only, configured as `gpt-5.6-luna`, `gpt-5.6-terra` and `gpt-5.6-sol`.

What is genuinely good: path-traversal protection on file APIs, hardened Docker flags, SHA-based
optimistic locking on edits, strict JSON schema for worker output, a per-job dollar budget,
rejection of no-op or destructive repair patches, consistent secret redaction.

---

## 2. Critical — fix before anyone else uses it

### 1. No authentication or tenant isolation
- **Where:** every route in `api/routes/*`; `docker-compose.yml` binds the API to `0.0.0.0:8000` and
  Redis to `6379` with no password; `backend/migrations/001_initial_supabase.sql` creates tables
  without Row Level Security.
- **Why it matters:** anyone who can reach the API can start unlimited jobs on your OpenAI budget,
  read and edit every project, and (with provider actions on) push to GitHub or create billable
  Supabase projects. The public Supabase anon key can read every prompt.
- **Fix:** add users and auth (the Next.js gateway can own it with Clerk or Better Auth and pass a
  signed user id); scope every job query by user; enable RLS on all tables; bind services to
  localhost in compose; add per-user rate and budget limits.

### 2. Failures silently become "success" with a generic template
- **Where:** `agents/workers/base.py:84-129`; planner, design and evaluator also swallow all
  exceptions (`agents/planner_agent.py:57`, `agents/design_director_agent.py:26`,
  `agents/evaluator_agent.py:64`). Unknown model names raise in the price table
  (`observability/cost_ledger.py:172`) and are then swallowed the same way.
- **Why it matters:** a wrong model name, truncated output or a code bug produces a starter
  template marked SUCCEEDED. Users get something generic and nobody can tell why.
- **Fix:** fail loudly. Mark the job `degraded` (new status) when `used_fallback` is true, include
  the reason, log and alert on it. Never catch-all in agents; catch only expected provider errors.
  The new studio already shows a banner when `used_fallback` is set.

### 3. No real job system
- **Where:** `api/routes/jobs.py:77` runs builds in FastAPI `BackgroundTasks` inside the web
  process. The Redis queue is only used when `run_immediately=false`, and only `/work-next` drains it.
- **Why it matters:** a restart or crash kills every running build. Those jobs stay `running`
  forever and `/run` refuses them with 409 (`jobs.py:122`). Builds cannot be cancelled and there is
  no overall timeout. Throughput is one process's thread pool.
- **Fix:** separate worker processes pulling from Redis (arq, Celery or RQ). Workers hold a lease
  with heartbeats; a reaper re-queues expired leases on startup. Add `POST /jobs/{id}/cancel` and a
  job-level timeout.

### 4. Model configuration is unverified and brittle
- **Where:** `config/settings.py:24-37`; `.env.example` lines 7-20; the README suggests a different
  model (`gpt-5.4`).
- **Why it matters:** if these model IDs do not exist for the key in use, every call fails and item 2
  hides it. Pricing is matched by prefix, so dated snapshots are priced wrongly (`cost_ledger.py:169`).
- **Fix:** validate the configured models at startup with one cheap call and refuse to start if they
  fail; treat unknown prices as a warning with a conservative default rather than an exception.

---

## 3. High — these decide quality, speed and cost

### 5. The pipeline runs one step at a time, and each worker writes everything in one call
- **Where:** `orchestration/state_machine.py:791-797` (workers in a fixed order in one loop);
  `integrations/llm_client.py:104` (blocking, no streaming); output caps of 12k/10k/16k tokens
  including reasoning (`state_machine.py:113-130`).
- **Why it matters:** total time is the sum of every call. Larger apps hit the output cap; that error
  is treated as fatal (`base.py:198`) and falls back to a template (item 2). Nothing reaches the
  user until a whole worker finishes.
- **Fix:** contract first: the planner emits the API contract (OpenAPI) and data schema, then
  database, backend and frontend run in parallel with LangGraph `Send`. Inside each worker, plan the
  file list first, then generate files in parallel (5-10 at a time). Stream tokens or finished files
  to the gateway.

### 6. One huge job object is copied everywhere
- **Where:** `models/job_state.py:201-203` (`manifest_state` holds every generated file's content);
  serialized at every graph node (`state_machine.py:701,716`), on every progress save with a new
  Postgres connection (`persistence/job_store.py:109`), and 50 at a time by `GET /api/jobs`.
  The end of a run overwrites the whole object (`state_machine.py:1069`), losing concurrent changes.
- **Why it matters:** cost grows with steps × project size; the job list endpoint returns megabytes;
  writes made during a run (for example a preview downgrade) are lost.
- **Fix:** store file contents separately (disk or S3, keyed by hash); keep job metadata small; record
  progress in an append-only `job_events` table; use a connection pool; add a slim
  `GET /api/jobs/{id}/summary` and paginate the list.

### 7. Validation is keyword-based and edits tests until they pass
- **Where:** `artifacts/validation.py:1188` (an `<input>` tag counts as "uses PUT"), `:2324`, `:2340`,
  `:67` (`/re/.exec()` flagged as Python exec); `capabilities/validation_adapters.py:404-418`
  ("decimal" in a comment passes money checks); `artifacts/file_manifest.py:711-723` rewrites
  generated tests; `validation.py:79-103` classifies app timeouts and `ECONNREFUSED` as
  infrastructure, skipping repair and shipping as provisional.
- **Why it matters:** repair rounds (an LLM call plus a Docker cycle each) chase false failures,
  real failures pass, and there is no reliable quality signal.
- **Fix:** judge by execution: install, typecheck, tests, build, then a Playwright smoke test against
  the running app. Parse code with real parsers (Python `ast`, TypeScript compiler) where static
  checks remain. Never modify generated tests. Only classify Docker/daemon failures as infrastructure.

### 8. Validation reinstalls everything, every attempt
- **Where:** `artifacts/validation.py:569-610` (fresh `docker run --rm`, `HOME` on tmpfs so no npm or
  pip cache, `--cpus 1.0`, components checked one after another); a separate lockfile container
  (`:612`); the preview builds yet another image.
- **Why it matters:** probably the largest share of wall-clock time per job, repeated up to 4 times.
- **Fix:** pre-built image per stack with dependencies installed; a shared read-only package cache;
  check components in parallel; fast checks (typecheck, lint) first; one warm container per job
  reused across repairs and for the preview.

### 9. Keyword stack detection picks the wrong stack
- **Where:** `capabilities/registry.py:282-305`, `_has_term` at `:396`.
- **Why it matters:** "website for an express courier service" becomes a backend-only Express API
  with no frontend; "not using Next.js" selects Next.js; everything else defaults to React + FastAPI.
- **Fix:** let the planner choose the stack with structured output, constrained to the certified
  packs; keep the user's explicit choice as an override.

### 10. Previews serialize every user and block for minutes
- **Where:** `sandbox/preview_manager.py:120-196` holds one global lock across the Docker build and
  Playwright check; `POST /preview` blocks until done; proxy containers are created without `--rm`
  and cleanup relies on `atexit` (`:640-667`).
- **Why it matters:** one slow preview freezes preview status, stop and logs for every job;
  crashed processes leave containers holding ports.
- **Fix:** a lock per job; start asynchronously (202, then status); label containers and clean
  orphans on startup; long term, run previews on a separate service (Fly Machines, Firecracker,
  E2B-style sandboxes).

### 11. Everything is in memory, and checkpoints leak
- **Where:** job store, queue, previews, collaboration hub, metrics, LangGraph checkpointer; the
  global `InMemorySaver` keeps every checkpoint with full file contents forever
  (`memory/langgraph_memory.py:30`); `ENABLE_LANGGRAPH_CHECKPOINTING` is ignored (`:42`).
- **Why it matters:** memory grows until restart; two instances would disagree about everything.
- **Fix:** Postgres as the source of truth, a Postgres checkpointer with retention, Redis for pub/sub
  and queueing, Prometheus or OpenTelemetry for metrics.

### 12. No projects or versions, so no real edits
- **Where:** the only entity is a job. There is no endpoint to change an existing project.
- **Why it matters:** the core Lovable loop ("make the header blue") is impossible. The studio works
  around it by building a whole new version from the original request plus a list of changes.
- **Fix:** data model `User → Project → Version (file set) → Run (create | edit | repair)`. An edit run
  sends the current files plus the change and applies the returned patches, then re-validates.

---

## 4. Medium — correctness and operations

### 13. Docker Compose cannot validate or preview anything
- **Where:** `backend/Dockerfile` (no Docker CLI, no Node, Playwright browsers never installed);
  settings paths resolve under `/usr/local/lib` for a non-editable install (`config/settings.py:13,80-82`).
- **Why it matters:** in Compose every build fails validation and the browser check always fails,
  which downgrades every job to provisional and locks publishing (`preview_manager.py:851-865`).
- **Fix:** install Node and Playwright Chromium in the image; talk to Docker through a socket or a
  separate sandbox service; set path settings explicitly in Compose.

### 14. Editing a verified build bypasses the release gate
- **Where:** `api/routes/workspace.py` (file `PUT`); `guardrails/release_policy.py:62`.
- **Why it matters:** after an edit, the build keeps `verified`, is not rescanned for secrets or
  vulnerabilities, and can be pushed to GitHub.
- **Fix:** any edit sets the release to `pending` and re-runs output guardrails before publishing.

### 15. Read-only paths can be edited
- **Where:** `api/routes/workspace.py:51` checks the raw path string, so `./artifacts/x` or
  `src/../artifacts/x` passes.
- **Fix:** check the resolved path relative to the project root, not the input string.

### 16. Design-token `PUT` ignores the editor flag
- **Where:** `api/routes/workspace.py:125-131`.
- **Fix:** apply the same `ENABLE_BROWSER_EDITOR` check as the file `PUT`.

### 17. Race conditions can run one job twice
- **Where:** check-then-act in `POST /run` and `POST /feedback` (`api/routes/jobs.py:83,122`).
- **Fix:** an atomic status transition (compare-and-set in the store, or a row lock).

### 18. A reachable crash for backend-only stacks
- **Where:** `orchestration/repair_kernel.py:397` and `:542-545`: when validation fails with no
  retry target, blame defaults to the frontend; a backend-only stack has no frontend task, so
  `next()` raises `StopIteration` and kills the job.
- **Fix:** derive the default target from the stack's actual tasks.

### 19. LangGraph is used against its grain
- **Where:** every node rebuilds the job from a dict; approval gates end the graph and re-run it from
  START; a custom manifest checkpoint system (`memory/manifest_checkpoint.py`) duplicates the
  LangGraph checkpointer.
- **Fix:** small typed graph state (ids and file references), `interrupt()` / `Command(resume=…)` for
  approvals, one checkpoint mechanism.

### 20. Output caps are likely too tight
- **Where:** design runs at high reasoning effort with an 1,800-token cap (`state_machine.py:113`);
  reasoning tokens count against the cap.
- **Fix:** raise the caps per role, or lower reasoning effort where the cap must stay small; treat
  "incomplete" as retryable with a larger cap.

### 21. Security edges that matter once it is exposed
- WebSocket collaboration has no Origin check, and bad JSON leaks sockets (`workspace.py:205-218`).
- The browser tool (when enabled) can fetch localhost and cloud metadata (`tools/policy.py:25-37`).
- `PREVIEW_SANDBOX_MODE=local` runs generated `npm`/`pip` scripts on the host (`preview_manager.py:363-396`).
- Absolute server paths are returned by `/files` and `/artifacts`.
- **Fix:** Origin allow-list; private-IP block for outbound tools; forbid local preview mode outside
  development; return relative paths only.

### 22. Test mode skips lockfile generation, so test previews fail
- **Where:** validation is skipped in test mode (`structural_validation:skipped_in_test`), and that is
  also where `package-lock.json` is regenerated; `npm ci` then rejects the stale lockfile.
- **Fix:** keep lockfile generation outside validation, or generate it from the certified template.

### 23. No response models on the API
- **Where:** handlers return plain dicts, so OpenAPI has no response shapes.
- **Why it matters:** frontend types are hand-written (`frontend/lib/backend/types.ts`) and drift silently.
- **Fix:** Pydantic response models on every route; the frontend can then generate types.

### 24. CI and tests miss real problems
- CI runs only `pytest` and the frontend build. `ruff` reports 4 errors and `mypy` 39; neither runs.
- Nothing exercises Docker, npm or previews by default (the two integration tests are opt-in).
- Unit tests write ZIPs and project folders into the real `artifacts/` and `generated-projects/`.
- **Fix:** add ruff, mypy and `npm audit` to CI; one scheduled integration job with Docker; point
  tests at temporary directories.

---

## 5. Product limitations users will notice (labelled in the studio today)

1. **A change rebuilds the whole project.** Needs item 12.
2. **"Request changes" at an approval gate cannot be undone,** and there is no cancel for a running
   build. Needs item 3 (cancel) and versions (item 12) to roll back.
3. **No accounts:** everyone sees every project. Needs item 1.
4. **Previews take minutes** on first start. Items 8 and 10.
5. **Publishing requires a verified build and a configured GitHub token;** in Compose builds never
   become verified (item 13).

---

## 6. Suggested order of work

| Step | Items | Outcome |
| --- | --- | --- |
| 1 | 2, 4, 23, 24 | Failures are visible and measurable; types stop drifting |
| 2 | 3, 17, 18 | Builds survive restarts, can be cancelled, do not double-run or crash |
| 3 | 1, 14, 15, 16, 21 | Safe to put in front of other people |
| 4 | 6, 11 | Fast, small state; can run more than one instance |
| 5 | 8, 10, 13, 22 | Validation and previews are fast and work in Docker |
| 6 | 5, 9, 20 | Parallel, streamed generation that picks the right stack |
| 7 | 12, 19 | Real edits and versions; the core Lovable loop |
| 8 | 7 | Trustworthy quality signal by execution |

## 7. What the frontend already handles

The new studio (branches `feat/frontend-phase-1-design-system` and `feat/frontend-phase-2-3-studio`)
streams builds through a gateway, survives reloads, shows template fallbacks, approval gates, real
validation results and cost, and labels the limitations above. When the backend adds an event
stream (item 5), versions (item 12) or auth (item 1), the gateway is the single place that changes.
