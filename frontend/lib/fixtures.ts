/**
 * Hand-written fixtures for every UI state, typed against the draft event
 * contract. Phase 0 replaces these with sequences recorded from real runs.
 */
import type {
  CheckpointPart,
  FilePart,
  ReleasePart,
  StagePart,
  ValidationPart,
} from "@/lib/contract";

export const PROMPT =
  "Build a customer portal for a coffee subscription: sign-in, plan management, delivery calendar, and an admin view for roasters.";

export const PROJECT_NAME = "Roastery Portal";

export const LONG_PROJECT_NAME =
  "Northwind Specialty Coffee Subscription Management Portal With Roaster Scheduling And Regional Delivery Calendars";

export const ASSISTANT_SUMMARY = `Planned a **React + FastAPI** project with PostgreSQL.

- Customers sign in, pause or change plans, and pick delivery windows.
- Roasters get an admin view of upcoming batches grouped by region.
- Payments stay out of scope until a provider is chosen.

Implementation is running now; files appear in **Code** as each worker finishes.`;

export const STAGES_BUILDING: StagePart[] = [
  { stage: "plan", status: "done", detail: "8 requirements, 3 workers" },
  { stage: "design", status: "done", detail: "Warm neutral palette, editorial type" },
  { stage: "database", status: "done", detail: "4 tables, 2 migrations" },
  { stage: "backend", status: "running", detail: "Writing subscription routes" },
  { stage: "frontend", status: "queued" },
  { stage: "validate", status: "queued" },
  { stage: "evaluate", status: "queued" },
  { stage: "release", status: "queued" },
];

export const STAGES_REVIEW: StagePart[] = [
  { stage: "plan", status: "review", detail: "Waiting for product contract approval" },
  { stage: "design", status: "queued" },
  { stage: "database", status: "queued" },
  { stage: "backend", status: "queued" },
  { stage: "frontend", status: "queued" },
];

export const STAGES_REPAIRING: StagePart[] = [
  { stage: "plan", status: "done" },
  { stage: "design", status: "done" },
  { stage: "database", status: "done" },
  { stage: "backend", status: "done" },
  { stage: "frontend", status: "running", attempt: 2, detail: "Repairing failing test in DeliveryCalendar" },
  { stage: "validate", status: "failed", detail: "1 of 14 checks failed" },
];

export const STAGES_VERIFIED: StagePart[] = [
  { stage: "plan", status: "done" },
  { stage: "design", status: "done" },
  { stage: "database", status: "done" },
  { stage: "backend", status: "done" },
  { stage: "frontend", status: "done" },
  { stage: "validate", status: "done", detail: "14 checks passed" },
  { stage: "evaluate", status: "done", detail: "All requirements met" },
  { stage: "release", status: "done", detail: "Verified" },
];

export const PLAN_STEPS = [
  "Model customers, plans, subscriptions and deliveries in PostgreSQL",
  "Expose FastAPI routes for auth, plan changes and delivery windows",
  "Build the customer dashboard and delivery calendar in React",
  "Add a roaster admin view with batches grouped by region",
  "Cover plan changes and calendar edge cases with tests",
];

export const CHECKPOINT: CheckpointPart = {
  checkpointId: "chk_7f2a",
  gate: "product_contract",
  title: "Approve the product contract",
  summary:
    "Three workers will build a React frontend, a FastAPI backend and a PostgreSQL schema. Payments are excluded until you choose a provider.",
  visual: `customers ──< subscriptions >── plans
                  │
                  └──< deliveries >── roast_batches`,
};

export const VALIDATION_PASSING: ValidationPart[] = [
  { name: "Install", command: "npm ci", passed: true, durationMs: 18_400 },
  { name: "Type check", command: "tsc --noEmit", passed: true, durationMs: 4_100 },
  { name: "Unit tests", command: "vitest run", passed: true, durationMs: 6_900 },
  { name: "Build", command: "vite build", passed: true, durationMs: 9_300 },
  { name: "API tests", command: "pytest -q", passed: true, durationMs: 7_700 },
];

export const VALIDATION_FAILING: ValidationPart[] = [
  { name: "Install", command: "npm ci", passed: true, durationMs: 17_900 },
  { name: "Type check", command: "tsc --noEmit", passed: true, durationMs: 3_900 },
  {
    name: "Unit tests",
    command: "vitest run",
    passed: false,
    durationMs: 7_200,
    excerpt: `FAIL src/components/DeliveryCalendar.test.tsx > skips paused weeks
AssertionError: expected [ '2026-10-05', '2026-10-12' ] to deeply equal [ '2026-10-12' ]
  at src/components/DeliveryCalendar.test.tsx:41:32`,
  },
];

export const FILES: FilePart[] = [
  { path: "backend/app/main.py", worker: "backend", bytes: 1_842, op: "create" },
  { path: "backend/app/routes/subscriptions.py", worker: "backend", bytes: 4_210, op: "create" },
  { path: "backend/app/models.py", worker: "database", bytes: 2_960, op: "create" },
  { path: "backend/migrations/001_initial.sql", worker: "database", bytes: 3_388, op: "create" },
  { path: "frontend/src/App.tsx", worker: "frontend", bytes: 1_204, op: "create" },
  { path: "frontend/src/components/DeliveryCalendar.tsx", worker: "frontend", bytes: 5_611, op: "patch" },
  {
    path: "frontend/src/features/roaster-admin/components/regional-batch-schedule/RegionalBatchScheduleTableRowWithInlineEditing.tsx",
    worker: "frontend",
    bytes: 7_942,
    op: "create",
  },
];

export const CODE_SAMPLE = `import { useMemo } from "react";

import { formatWeek, weeksBetween } from "../lib/dates";
import type { Delivery, Subscription } from "../types";

interface DeliveryCalendarProps {
  subscription: Subscription;
  deliveries: Delivery[];
}

export function DeliveryCalendar({ subscription, deliveries }: DeliveryCalendarProps) {
  const weeks = useMemo(
    () => weeksBetween(subscription.startsOn, subscription.renewsOn),
    [subscription.startsOn, subscription.renewsOn],
  );

  return (
    <ol className="calendar">
      {weeks.map((week) => {
        const paused = subscription.pausedWeeks.includes(week);
        const delivery = deliveries.find((item) => item.week === week);
        return (
          <li key={week} data-paused={paused}>
            <span>{formatWeek(week)}</span>
            {delivery ? <span>{delivery.status}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}`;

export const PREVIEW_LOGS = `\u001b[2m08:14:02\u001b[0m frontend  VITE v8.3.1  ready in 412 ms
\u001b[2m08:14:02\u001b[0m frontend  ➜  Local:   http://127.0.0.1:41873/
\u001b[2m08:14:03\u001b[0m backend   INFO:     Started server process [7]
\u001b[2m08:14:03\u001b[0m backend   INFO:     Application startup complete.
\u001b[2m08:14:05\u001b[0m backend   INFO:     127.0.0.1 - "GET /api/plans HTTP/1.1" \u001b[32m200\u001b[0m
\u001b[2m08:14:06\u001b[0m backend   \u001b[33mWARNING\u001b[0m:  Slow query on deliveries (412 ms)
\u001b[2m08:14:07\u001b[0m frontend  hmr update /src/components/DeliveryCalendar.tsx`;

export const RELEASE_VERIFIED: ReleasePart = { status: "verified", usedFallback: false, costUsd: 0.184 };

export const RELEASE_FALLBACK: ReleasePart = { status: "provisional", usedFallback: true, costUsd: 0.041 };

export const COST = { spentUsd: 0.184, budgetUsd: 1, promptTokens: 48_210, completionTokens: 21_560 };

export const JOB_STATUSES = [
  "pending",
  "running",
  "evaluating",
  "retrying",
  "awaiting_human_feedback",
  "succeeded",
  "failed",
  "blocked",
] as const;

export const STAGE_STATUSES = ["queued", "running", "review", "done", "failed"] as const;

export const RELEASE_STATUSES = ["pending", "verified", "provisional", "quarantined"] as const;
