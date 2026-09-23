# Architecture

The system follows a guarded, checkpointed LangGraph workflow:

1. The API accepts a user request with HTTP `202` and starts background processing.
2. A job state is created, persisted, and optionally stored in Redis for queued execution.
3. The durable parent graph runs input guardrails, planning, design, approval, worker, validation,
   evaluation, routing, retry/replan, release approval, and terminal finalization as explicit nodes.
4. Project context is loaded from the LangGraph Store; production uses Supabase/Postgres.
5. A deterministic policy records positively requested and explicitly excluded capabilities.
6. The capability registry resolves a versioned `ProjectSpec` for one of the certified initial stacks.
7. The planner creates only the workers required by that pack; a database worker is added only for a positive persistence request.
8. Workers return scoped replacement or patch manifests. A nested LangGraph repair subgraph merges them into a canonical path-indexed manifest and checkpoints every successful attempt before review or validation.
9. Tool calls pass through the allowlisted, permission-checked, timed, and redacted MCP boundary.
10. Meaningful first attempts can pause at a capped human checkpoint. Automatic validation repairs do not create redundant approval prompts.
11. Output guardrails scan worker output for sensitive data, leaked secrets, and risky code patterns.
12. The artifact writer rejects path conflicts, applies exclusion policy, and writes into staging.
13. Certified capability policy overrides core Node framework versions before npm deterministically creates lockfiles.
14. Structural checks dispatch by stack and verify dependency strategies, tests, README references, configuration examples, safe scripts, and hidden files.
15. Executable checks create isolated dependency environments, run tests and builds, block high production dependency risks, block critical development-tool risks, record high development advisories, and execute shared API contracts where applicable.
16. The ZIP file list is compared with the validated staging directory.
17. Only a passing directory and ZIP are atomically moved to public artifact locations.
18. The evaluator checks actual command evidence rather than worker success claims.
19. The router returns success, failure, human feedback, or a targeted retry with the exact failure.

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
