# Retry Policy

The runtime uses targeted retries instead of replaying the entire job:

- Each worker has a maximum attempt budget.
- The whole job has a 12-attempt aggregate budget, allowing database, backend, and frontend workers to each reach the four-attempt ceiling when genuinely necessary.
- Rejected repair candidates and human-approval resumptions do not reduce those official attempt budgets.
- The loop interceptor allows up to 12 worker execution cycles, matching the aggregate four-attempt allowance across database, backend, and frontend workers; approval-only resumptions do not consume this budget. One bounded automatic replan uses `MAX_AUTOMATIC_REPLANS` and starts a fresh repair-loop counter so it cannot steal the regenerated plan's worker attempts.
- The evaluator returns retry targets by worker kind.
- Retry feedback includes the exact failure plus the complete checkpointed project manifest.
- Multiple planner tasks for the same worker are collapsed before execution.
- Per-worker usage is based on the highest attempt for that worker, not a sum of duplicate tasks.
- The router schedules only allowed retry targets or fails cleanly when retry budget is exhausted.
- Worker attempts are reserved for accepted code generations and evidence-backed code repairs.
- Registry, network, Docker-daemon, and audit timeouts use a separate infrastructure retry path and never consume worker attempts.
- Once an evidence-backed code repair begins, the cost ledger enters repair phase so the repaired build's evaluator and release checks use the hard repair ceiling instead of failing against the normal-run ceiling.
- Validation records the failing phase (`dependency_install`, `tests`, `build`, or `dependency_security`) so infrastructure failures cannot masquerade as frontend failures.
- A failed external dependency audit opens a short-lived circuit breaker; repeated audits are skipped, the runnable build remains available, and publication stays provisional.
- LangGraph reducers preserve unchanged files, apply scoped repair patches, and retain explicit deletion tombstones.
- The last executable manifest is checkpointed independently and restored if a later final repair fails.
- Human-requested changes reset only the checkpointed worker task and preserve the rest of the job state.
- Automated validation repairs skip redundant human checkpoints; user-requested revisions receive a fresh review.
- Internal artifact failures without a responsible worker fail safely instead of repeatedly replanning.
- Premium repair is reserved for the final evidence-backed patch, repeated rejected candidates, proven semantic requirement gaps, and database defects; earlier deterministic, test-contract, dependency, and build repairs stay on the standard repair model.
- If every initial response-contract recovery fails, a certified runnable checkpoint is committed and validated, then the responsible worker receives a targeted patch ticket. It can remain previewable/downloadable but cannot silently pass semantic evaluation.
- Per-node model authorizations are bounded independently from dollar and worker-attempt budgets.
- Every targeted repair uses a `repair.*` model node, so the ledger enters the explicit repair phase before the normal-run ceiling can starve another worker.
