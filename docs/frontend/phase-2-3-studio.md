# Phases 2 and 3 — Streaming Gateway and Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the new studio build real projects: a Next.js gateway turns backend jobs into an AI SDK
UI message stream, and a studio at `/studio` renders it with chat, live preview, code editing,
activity and publishing.

**Architecture:** The Python API is unchanged. `POST /api/chat` creates a job and streams it;
`GET /api/chat/[jobId]/stream` re-attaches to a running job. Both poll the job server-side, translate
it with a pure `jobToParts` function into reconciled `data-*` parts, and write only the parts that
changed. Every stream opens with `start { messageId: "job-<id>" }` and the full snapshot, so a
resumed stream replaces the assistant message wholesale (verified in `ai` 6.0: a `start` chunk whose
`messageId` matches the last message triggers `replaceMessage`). Plain REST calls (files, preview,
providers, feedback, download) go through the existing `/api/*` fallback rewrite to Python.

**Tech Stack:** Next.js 16 route handlers, `ai` 6 (`createUIMessageStream`), `@ai-sdk/react`
`useChat`, TanStack Query 5, CodeMirror 6 via `@uiw/react-codemirror`, Vitest.

**Spec:** `docs/frontend/roadmap.md` (Phases 2–3) and `docs/frontend/phase-1-design-system.md`
(design rules still apply everywhere).

## Global Constraints

- Everything from the Phase 1 design brief (tokens, motion, banned patterns); `tests/design-rules.test.ts` stays green.
- The backend is not modified. Anything the backend cannot do is labelled honestly in the UI.
- Gateway talks to `BACKEND_URL` (runtime env, default `http://localhost:8000`).
- Rewrite proxy timeout raised to 10 minutes (`experimental.proxyTimeout`), because
  `POST /api/jobs/{id}/preview` blocks while Docker builds; the Next default is 30 s.
- Poll interval 1 s server-side; the browser never polls job state.
- Every part carries a stable `id` so re-emission is idempotent.

## Review Focus

1. **Page reload mid-build** must reattach and show current progress, not an empty chat or duplicate parts.
2. **Approval checkpoints**: approving must continue the same assistant message; a second click must be impossible.
3. **Backend down or 4xx/5xx** (prohibited prompt returns 422 with a structured `detail`) must show a readable error, not a stuck spinner.
4. **Unsaved edits** in the code editor must survive switching tabs and warn before switching files; a SHA conflict (409) must not overwrite someone else's change.
5. **Template fallback** (`worker_results[].used_fallback`) must be visible on the result.

---

## Contract changes (`lib/contract.ts`)

Replace `release`, `preview` and `notice` parts with:

```ts
job: {
  status: string;              // backend JobStatus
  releaseStatus: ReleaseStatus;
  costUsd: number;
  budgetUsd: number;
  usedFallback: boolean;
  error?: string;              // last error or evaluation failure reason
  artifactsReady: boolean;     // folder + zip exist
};
summary: { text: string };     // markdown; reconciled so resume never duplicates it
```

`checkpoint` gains `status: "pending" | "approved" | "changes_requested" | "auto_approved"`,
`prompt: string` and `response?: string`. `ForgeMessageMetadata` gains `basedOnJobId?: string`.

## Stage derivation (pure, tested)

| Stage | Rule |
| --- | --- |
| plan | `review` if active gate is `product_contract`; `done` if tasks exist; `running` if job live; else `queued` |
| design | `done` if `design_spec.product_summary`; `running` if plan done and live; else `queued` |
| database / backend / frontend | only for tasks that exist; `pending`→`queued`, or `running` for the first pending task while the job is live and not awaiting feedback; `succeeded`→`done`; `failed`→`failed`; `attempt` carried |
| validate | `done`/`failed` from folder artifact `metadata.validation.passed`; `running` when all tasks done, live, no artifacts |
| evaluate | `running` when status `evaluating`; `done` when `evaluation.passed`; `failed` when evaluation failed |
| release | `review` if active gate is `release`; `done` when terminal with verified/provisional; `failed` when quarantined, failed or blocked |

A terminal `failed`/`blocked` job with no failed stage marks the first unfinished stage `failed`.

## File structure

```
frontend/
  app/api/chat/route.ts                     POST: create job (or follow-up), stream it
  app/api/chat/[jobId]/stream/route.ts      GET: reattach to a live job, 204 otherwise
  app/studio/page.tsx                       new project
  app/studio/[jobId]/page.tsx               server: fetch job chain, render Studio
  app/studio/layout.tsx                     QueryClientProvider
  lib/backend/types.ts                      backend JobState subset (hand-typed)
  lib/backend/client.ts                     server-side fetch helpers (BACKEND_URL)
  lib/gateway/translate.ts                  jobToParts, jobToMessage, conversationFromJobs
  lib/gateway/stream.ts                     streamJob(writer, jobId, signal)
  lib/gateway/prompt.ts                     follow-up prompt composition
  lib/gateway/__fixtures__/*.json           recorded snapshots (trimmed)
  components/studio/studio.tsx              client root: useChat + layout switch
  components/studio/new-project.tsx         centred composer + recent projects
  components/studio/chat-panel.tsx          conversation + composer
  components/studio/assistant-message.tsx   renders data parts
  components/studio/workspace-panel.tsx     tabs: preview / code / activity
  components/studio/preview-tab.tsx
  components/studio/code-tab.tsx
  components/studio/code-editor.tsx         CodeMirror, dynamic import
  components/studio/activity-tab.tsx
  components/studio/publish-menu.tsx        ZIP + GitHub dialog
  lib/studio/api.ts                         browser REST helpers + query keys
```

---

### Task 1: Translator (Phase 2 core)

**Files:** `lib/backend/types.ts`, `lib/gateway/translate.ts`, `lib/gateway/translate.test.ts`,
`lib/gateway/__fixtures__/` (recorded from a test-mode backend: running, awaiting product contract,
awaiting release, succeeded; plus hand-edited failed, repairing and fallback variants), `lib/contract.ts`.

**Produces:**
- `isLive(job: BackendJob): boolean` — status in pending/running/evaluating/retrying
- `jobToParts(job: BackendJob): ForgePart[]` where `ForgePart = { type: \`data-${K}\`; id: string; data: ForgeDataParts[K] }`
- `jobToMessage(job: BackendJob): ForgeMessage` — assistant message `job-<id>` with metadata
- `conversationFromJobs(chain: BackendJob[]): ForgeMessage[]` — user + assistant per job, oldest first

- [ ] Write tests: stage table rows above against fixtures; checkpoint pending/approved; files from `manifest_state.files` (deleted excluded, `revision > 1` → `patch`); validation from `validation_results`; `job` part fallback and error; summary for running, review, succeeded, failed; unknown status never throws.
- [ ] Run → fail. Implement. Run → pass. Commit.

### Task 2: Stream and routes

**Files:** `lib/backend/client.ts`, `lib/gateway/stream.ts`, `lib/gateway/prompt.ts`,
`app/api/chat/route.ts`, `app/api/chat/[jobId]/stream/route.ts`, tests for stream + prompt, `next.config.ts`.

- `streamJob({ writer, fetchJob, jobId, signal, intervalMs })`: write `start` with messageId and metadata, full snapshot, then every interval write parts whose serialised data changed; stop when not live (after final write), when aborted, or after 3 consecutive fetch errors (write `error`).
- `POST`: parse `{ messages, projectName?, capabilityId?, basedOnJobId? }`; last user text is the request; follow-ups compose `buildFollowUpPrompt(original, change)` and store `display_prompt` and `based_on_job_id` in job metadata; backend 422 → stream an `error` chunk with the policy message.
- `GET`: job live → stream; else 204.
- [ ] Tests (node environment, mocked fetch): snapshot then diff only; stop on terminal; abort stops polling; 422 surfaces message; follow-up prompt text. Commit.

### Task 3: Studio shell and chat (Phase 3)

- `/studio`: centred composer (prompt, project name, stack select), recent projects from `GET /api/jobs` (status badge, relative time).
- `/studio/[jobId]`: server fetches the job and its `based_on_job_id` chain (max 10), passes `initialMessages` and `resume = isLive(latest)`.
- `Studio` client: `useChat<ForgeMessage>` with `id = jobId ?? generated`, `DefaultChatTransport` (`prepareSendMessagesRequest` adds project name, capability and `basedOnJobId`; `prepareReconnectToStreamRequest` targets the active job). When a stream's metadata carries a new `jobId`, replace the URL with `/studio/<jobId>` without remounting.
- Assistant message renders summary, stage list, plan (from checkpoint contract), checkpoint card (approve/request changes → `POST /api/jobs/{id}/feedback` then `resumeStream()`), files written (collapsible), validation results, job outcome (release badge, fallback notice, error alert, cost).
- Composer on an existing project says "New version" and explains it rebuilds with the requested change.
- [ ] Component tests: assistant message renders each part type; checkpoint calls feedback then resume. Commit.

### Task 4: Workspace tabs

- **Preview:** `GET /preview` (404 = not started), start (blocking; show staged starting state), stop, logs in terminal, device toggle, open in new tab, iframe `sandbox="allow-scripts allow-same-origin allow-forms allow-popups"` (cross-origin sandbox URL), screenshot fallback after a load timeout. Auto-start once when artifacts become ready.
- **Code:** file tree from `GET /files` (from stream `file` parts while building), CodeMirror editor with language by extension, `⌘S` save with `expected_sha256`, 409 → conflict dialog (reload theirs / keep mine), unsaved guard on file switch, read-only for non-text files.
- **Activity:** stages, validation, cost, guardrail findings, errors and warnings.
- **Publish menu:** download ZIP; GitHub sync dialog enabled only for verified builds with the provider configured.
- [ ] Tests for pure helpers (language detection, sha256, conflict handling reducer). Commit.

### Task 5: Verify end to end

- [ ] Lint, typecheck, tests, build.
- [ ] Browser run against a test-mode backend with checkpoints: new project → approve contract → approve release → preview → edit a file → save → reload mid-build.
- [ ] Browser run against the development backend with a real key if available.
- [ ] Whole-branch review; fix findings.

## Out of scope (labelled in the UI or docs)

- Incremental edits: the backend has no revision endpoint, so follow-ups build a new version from scratch.
- Collaboration presence, design-token editor, Supabase provisioning, revision diff viewer.
- Auth (Phase 4).
