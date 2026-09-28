# Architecture

The system follows a guarded, checkpointed LangGraph workflow:

1. The API accepts a user request with HTTP `202` and starts background processing.
2. A job state is created, persisted, and optionally stored in Redis for queued execution.
3. The durable parent graph runs input guardrails, deterministic preflight, upfront scope/profile/budget
   approval, planning, design, optional privileged approval, worker, validation,
   evaluation, routing, retry/replan, release approval, and terminal finalization as explicit nodes.
4. Project context is loaded from the LangGraph Store; production uses Supabase/Postgres.
5. A deterministic policy records positively requested and explicitly excluded capabilities.
6. The capability registry resolves a versioned `ProjectSpec` for one of the certified initial stacks.
7. The planner creates only the workers required by that pack; a database worker is added only for a positive persistence request.
8. Workers return scoped replacement or patch manifests. A nested LangGraph repair subgraph merges them into a canonical path-indexed manifest and checkpoints every successful attempt before review or validation.
9. Tool calls pass through the allowlisted, permission-checked, timed, and redacted MCP boundary.
10. No paid planning begins until the user approves the generation profile and maximum spend. Automatic validation repairs do not create redundant approval prompts.
11. Output guardrails scan worker output for sensitive data, leaked secrets, and risky code patterns.
12. The artifact writer rejects path conflicts, applies exclusion policy, and writes into staging.
13. Certified capability policy overrides core Node framework versions before npm deterministically creates lockfiles.
14. Structural checks dispatch by stack and verify dependency strategies, tests, README references, configuration examples, safe scripts, and hidden files.
15. Executable checks create isolated dependency environments, run tests and builds, block high production dependency risks, block critical development-tool risks, record high development advisories, and execute shared API contracts where applicable.
16. The ZIP file list is compared with the validated staging directory.
17. Only a passing directory and ZIP are atomically moved to public artifact locations.
18. The evaluator checks actual command evidence rather than worker success claims.
19. The router returns success, failure, human feedback, or a targeted retry with the exact failure.
20. Prompt uploads are signature-validated, checkpointed as immutable asset references, optionally
    combined with downloaded or embedded media, copied only when referenced, and deleted from temporary
    storage after terminal completion. Voice recordings are transcribed into editable text and not retained.
21. After verified terminal completion, a conversational project explainer runs outside LangGraph.
    It uses one economical model with deterministic retrieval over redacted specifications,
    validation evidence, manifests, and bounded source excerpts. It permits ten prompts per build,
    caches repeats, enforces a one-cent budget, rejects code or modification requests before the
    model when possible, and has no write or execution capability.

## Runtime and Platform Plane

- The preview manager selects stack-native commands from `ProjectSpec`, allocates local ports,
  strips inherited credentials, captures logs, and owns start/stop lifecycle.
- Trusted development can use local subprocess previews. Production requires the Docker runner and
  its read-only filesystem, dropped capabilities, PID, CPU, and memory limits.
- Workspace writes use SHA-256 optimistic concurrency, external revision storage, atomic file
  replacement, collaboration broadcasts, and atomic ZIP regeneration.
- The visual editor can update existing CSS custom properties only; it cannot insert selectors or
  arbitrary declarations.
- GitHub and Supabase adapters are off by default, read tokens only from settings, map provider
  errors without returning credentials, and require explicit API actions.
- The platform has no third-party hosting adapter. Preview URLs are loopback-only and owned by the
  local or Docker sandbox until first-party domain and subdomain routing is implemented.
- The benchmark runner executes twelve stack and domain cases repeatedly and compares complete content
  digests to detect nondeterminism.
- The Studio project explainer is a separate conversational route with a compact project header,
  visible prompt allowance, cited evidence, and a persistent read-only boundary. Existing verified
  jobs are migrated into the conversational state through an idempotent API backfill.

The runtime defaults to LangGraph in-memory checkpoints and Store memory for local development.
Enabling `ENABLE_PERSISTENCE` writes job snapshots, graph checkpoints, and project memory to
Supabase/Postgres. Every job uses `<job-id>:workflow` as its durable parent-graph thread identity;
replans advance a manifest generation so stale files cannot re-enter the new plan. Enabling
`ENABLE_REDIS` routes queued jobs through Redis-compatible infrastructure.

Human checkpoints are controlled by `ENABLE_HUMAN_CHECKPOINTS` and capped by
`MAX_HUMAN_CHECKPOINTS`. MCP tool use is controlled by `ENABLE_MCP_TOOLS`; network tools require
their own flags and credentials. Generated applications are localhost-first. CI/CD, GitHub,
hosting, payments, databases, and other external integrations are included only when positively
requested.

Auto mode recommends a profile deterministically. Standard mode uses economical planning and design
with a maximum one-dollar authorization. Advanced mode reserves the user-approved ceiling for complex
full-stack, media, security, and repair work. The authorization is a ceiling, never a spending target;
the Global Cost Ledger rejects any paid call whose worst-case reservation would cross it.
