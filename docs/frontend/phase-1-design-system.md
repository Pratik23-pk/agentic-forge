# Phase 1 — Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Vite studio and its 4,000 lines of CSS with a Next.js 16 app whose dark,
restrained design system (tokens, motion, primitives, domain status components and restyled AI
Elements) is fully demonstrated on a `/dev/states` reference page.

**Architecture:** Next.js 16 App Router in `frontend/`, Tailwind CSS v4 with CSS-first tokens in
`app/globals.css`, shadcn/ui (Radix primitives, `radix-nova` style) for primitives, AI Elements
for AI-specific surfaces, and a thin `components/forge/` layer for product-specific pieces. The
Python API is reached through a Next.js `fallback` rewrite of `/api/*`, which leaves room for the
Phase 2 gateway routes under `/api/chat`.

**Tech Stack:** Next.js 16, React 19, TypeScript (strict), Tailwind CSS 4, shadcn/ui 4 (Radix),
AI Elements 1.x, lucide-react, Geist Sans/Mono (`geist` package), Vitest + Testing Library.

**Spec:** `docs/frontend/roadmap.md` (Phase 1 row) and the design brief below.

## Design brief

Subtle premium, professional, dark. The reference points are Linear, Vercel and Raycast, not
"AI product" marketing.

- **Neutral first.** Near-black cool neutrals (hue 264, chroma ≤ 0.006). Depth comes from three
  surface steps and hairline borders, not shadows or glow.
- **One accent, used sparingly.** "Ember" (`oklch(0.76 0.13 64)`) — a forge colour that avoids
  the purple/cyan AI cliché. Used for the brand mark, focus ring and the running indicator only.
  Primary buttons are near-white on dark.
- **Status is semantic.** `success`, `warning`, `danger`, `info` are muted and always paired with
  a label or icon; colour never carries meaning alone.
- **Type.** Geist Sans for UI, Geist Mono for code, paths, IDs and numbers. 14px app base,
  tight tracking on headings, `tabular-nums` for all figures.
- **Banned (AI slop):** gradient text, neon glows, glassmorphism blobs, animated gradient borders,
  sparkle icons as decoration, emoji, "✨ AI-powered" copy, orbit animations, fake progress
  percentages, drop shadows larger than 8px blur.
- **Motion (Emil Kowalski's rules).**
  - Custom curves only: `--ease-out-strong: cubic-bezier(0.23, 1, 0.32, 1)`,
    `--ease-in-out-strong: cubic-bezier(0.77, 0, 0.175, 1)`,
    `--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)`. Never `ease-in`.
  - Durations: press 120ms, tooltip 125–150ms, popover/dropdown 150–200ms, dialog 200ms. Nothing
    in the product UI over 300ms.
  - Pressables scale to `0.97` on `:active`. Entrances start at `scale(0.96)` + `opacity: 0`,
    never `scale(0)`. Popovers scale from `var(--transform-origin)`; dialogs stay centred.
  - Only `transform` and `opacity` animate. Hover effects gated behind
    `@media (hover: hover) and (pointer: fine)`.
  - Keyboard-initiated UI (command palette, shortcuts) does not animate.
  - `prefers-reduced-motion`: keep opacity/colour transitions, remove movement.
  - Streaming list items (stages, files) enter with a 180ms fade + 4px rise, staggered 40ms.

## Global Constraints

- Node ≥ 20.9 (local is 20.19.1); CI uses Node 22.
- Next.js 16.x, React 19.x, Tailwind CSS 4.x, TypeScript strict with `noUnusedLocals` and
  `noUnusedParameters`.
- Dev server stays on port **5173** so backend CORS (`localhost:5173`) and docs remain valid.
- Dark only: `<html class="dark">`, no theme toggle in Phase 1.
- Use semantic tokens (`bg-background`, `text-muted-foreground`, `bg-success/10`); no raw palette
  classes (`bg-zinc-900`, `text-emerald-500`) anywhere in `app/` or `components/forge/`.
- No `transition-all`, no `ease-in`, no animation longer than 300ms outside `/dev/states` motion demos.
- Every status indicator carries a text label or `aria-label`.
- No file from the old `frontend/src/` survives; old types are re-derived in `lib/contract.ts`.

## Review Focus

1. **Unknown status strings from the backend** (e.g. a new job status) must render a neutral
   "Unknown" badge instead of crashing — covered by a test in Task 4.
2. **Reduced motion** users must get no translate/scale animation — covered by the CSS rule in
   Task 2 and verified manually on `/dev/states`.
3. **Long file paths and long job names** must truncate, never break layouts — fixtures in Task 6
   include a 120-character path and name.
4. **Keyboard focus** must be visible on every interactive element against the dark surfaces —
   ember ring verified in Task 7.
5. **Production build without network** — fonts come from the `geist` package, not Google Fonts,
   so `next build` works offline and in CI.

---

## File structure

```
frontend/
  app/
    layout.tsx            root layout: fonts, dark class, Toaster, metadata
    globals.css           Tailwind import, tokens (@theme), base layer, motion, reduced motion
    page.tsx              holding page linking to /dev/states (studio returns in Phase 3)
    not-found.tsx
    dev/states/page.tsx   design-system reference, composed from sections below
  components/
    ui/                   shadcn primitives (generated, then motion-tuned)
    ai-elements/          AI Elements (generated, then restyled)
    forge/
      brand-mark.tsx      logo mark
      status.tsx          StatusDot, StatusBadge, ReleaseBadge
      stage-list.tsx      build stages with streaming entrance
      states/             one file per /dev/states section
  lib/
    utils.ts              cn()
    contract.ts           draft event contract types (ForgeMessage data parts)
    status.ts             status → tone/label mapping (pure, tested)
    fixtures.ts           typed fixtures for every UI state
  lib/status.test.ts
  next.config.ts          standalone output, /api fallback rewrite
  vitest.config.ts
  Dockerfile              Next standalone image
```

---

### Task 1: Scaffold Next.js in place of the Vite app

**Files:**
- Delete: `frontend/src/**`, `frontend/index.html`, `frontend/vite.config.ts`, `frontend/nginx.conf`,
  `frontend/tsconfig.json`, `frontend/package.json`, `frontend/package-lock.json`
- Create: Next.js app files listed above, `frontend/Dockerfile`, `frontend/vitest.config.ts`
- Modify: `docker-compose.yml` (frontend port `5173:3000`, `BACKEND_URL`), `.github/workflows/ci.yml`,
  `scripts/run_frontend.sh`, `README.md` (frontend section)

**Produces:** `npm run dev|build|lint|typecheck|test` in `frontend/`; `@/` import alias.

- [x] **Step 1:** `git rm -r` the old frontend sources and configs listed above.
- [x] **Step 2:** `npx create-next-app@latest frontend --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*" --use-npm --turbopack --yes`
- [x] **Step 3:** `npx shadcn@latest init --preset base-nova` inside `frontend/`.
- [x] **Step 4:** Set scripts: `"dev": "next dev -p 5173"`, `"typecheck": "tsc --noEmit"`,
  `"test": "vitest run"`; add `noUnusedLocals`/`noUnusedParameters` to `tsconfig.json`.
- [x] **Step 5:** `next.config.ts`:

```ts
import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }],
    };
  },
};

export default nextConfig;
```

- [x] **Step 6:** Vitest + Testing Library + jsdom; `vitest.config.ts` with the `@` alias.
- [x] **Step 7:** Dockerfile (Node 22 alpine, `npm ci`, `next build`, copy `.next/standalone`,
  `.next/static`, `public`; `CMD node server.js` on port 3000).
- [x] **Step 8:** CI frontend job: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- [x] **Step 9:** Verify `npm run build` and `npm run lint` pass. Commit
  `chore(frontend): replace Vite studio with Next.js 16 scaffold`.

### Task 2: Tokens, typography and motion

**Files:** Modify `frontend/app/globals.css`, `frontend/app/layout.tsx`

- [x] **Step 1:** Replace generated `globals.css` token blocks with a single dark token set:

```css
:root {
  --radius: 0.5rem;
  --background: oklch(0.145 0.004 264);
  --foreground: oklch(0.955 0.003 264);
  --card: oklch(0.172 0.004 264);
  --card-foreground: var(--foreground);
  --popover: oklch(0.19 0.005 264);
  --popover-foreground: var(--foreground);
  --primary: oklch(0.955 0.003 264);
  --primary-foreground: oklch(0.17 0.004 264);
  --secondary: oklch(0.215 0.005 264);
  --secondary-foreground: var(--foreground);
  --muted: oklch(0.2 0.005 264);
  --muted-foreground: oklch(0.68 0.008 264);
  --accent: oklch(0.235 0.006 264);
  --accent-foreground: var(--foreground);
  --destructive: oklch(0.66 0.19 25);
  --border: oklch(1 0 0 / 0.08);
  --input: oklch(1 0 0 / 0.1);
  --ring: oklch(0.76 0.13 64 / 0.7);
  --brand: oklch(0.76 0.13 64);
  --brand-foreground: oklch(0.2 0.03 64);
  --success: oklch(0.74 0.13 158);
  --warning: oklch(0.8 0.13 80);
  --danger: oklch(0.66 0.19 25);
  --info: oklch(0.72 0.1 245);
}
```

- [x] **Step 2:** Map them in `@theme inline` (`--color-brand`, `--color-success`, …), add
  `--font-sans`/`--font-mono` from Geist variables and the three easing curves as
  `--ease-out-strong`, `--ease-in-out-strong`, `--ease-drawer`.
- [x] **Step 3:** Base layer: `color-scheme: dark`, font feature settings, `::selection` in brand at
  30%, thin neutral scrollbars, `:focus-visible` ring (2px ring, 2px offset on background),
  `tabular-nums` utility for figures.
- [x] **Step 4:** Reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
  }
  [data-motion="rise"] { transform: none !important; }
}
```

- [x] **Step 5:** `layout.tsx`: `GeistSans.variable GeistMono.variable`, `className="dark"`,
  `antialiased`, metadata (`Agentic Forge`), `<Toaster />`.
- [x] **Step 6:** Build passes. Commit `feat(frontend): dark design tokens, type and motion system`.

### Task 3: Primitives, tuned for motion

**Files:** Create `frontend/components/ui/*` via CLI; modify `button.tsx` and overlay components.

- [x] **Step 1:** `npx shadcn@latest add button badge card input textarea separator skeleton tooltip
  dropdown-menu dialog tabs scroll-area resizable kbd spinner sonner alert empty field select
  switch toggle-group progress collapsible`
- [x] **Step 2:** Read every generated file. Enforce: pressables use
  `transition-[transform,background-color,color,border-color,box-shadow] duration-150 ease-out-strong active:scale-[0.97]`;
  no `transition-all`; popover, dropdown, select and tooltip content use
  `origin-(--transform-origin)` with a 150ms enter from `scale-[0.96] opacity-0`; dialogs enter
  200ms from `scale-[0.97] opacity-0`, centred; exits are shorter than entrances.
- [x] **Step 3:** Build + lint pass. Commit `feat(frontend): shadcn primitives with motion tuning`.

### Task 4: Contract draft and status system

**Files:** Create `frontend/lib/contract.ts`, `frontend/lib/status.ts`, `frontend/lib/status.test.ts`,
`frontend/components/forge/status.tsx`

**Produces:**
- `type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info"`
- `describeJobStatus(status: string): { label: string; tone: Tone; live: boolean }`
- `describeStageStatus(status: string): { label: string; tone: Tone; live: boolean }`
- `describeRelease(status: string): { label: string; tone: Tone; description: string }`
- `<StatusDot tone live />`, `<StatusBadge status kind="job" | "stage" />`, `<ReleaseBadge status />`

- [x] **Step 1: Failing tests** in `lib/status.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { describeJobStatus, describeRelease, describeStageStatus } from "./status";

describe("describeJobStatus", () => {
  it("marks running work as live brand", () => {
    expect(describeJobStatus("running")).toEqual({ label: "Building", tone: "brand", live: true });
  });
  it("maps awaiting_human_feedback to a review state", () => {
    expect(describeJobStatus("awaiting_human_feedback")).toEqual({
      label: "Needs review", tone: "warning", live: false,
    });
  });
  it("falls back to a neutral label for unknown statuses", () => {
    expect(describeJobStatus("teleporting")).toEqual({ label: "Unknown", tone: "neutral", live: false });
  });
});

describe("describeStageStatus", () => {
  it("maps done to success", () => {
    expect(describeStageStatus("done").tone).toBe("success");
  });
});

describe("describeRelease", () => {
  it("explains quarantined builds", () => {
    const release = describeRelease("quarantined");
    expect(release.tone).toBe("danger");
    expect(release.description).toMatch(/publication is locked/i);
  });
});
```

- [x] **Step 2:** `npm test` → FAIL (module not found).
- [x] **Step 3:** Implement `lib/status.ts` with lookup tables for job statuses
  (`pending | running | awaiting_human_feedback | evaluating | retrying | succeeded | failed | blocked`),
  stage statuses (`queued | running | review | done | failed`) and release statuses
  (`pending | verified | provisional | quarantined`), each with an `Unknown` fallback.
- [x] **Step 4:** `npm test` → PASS.
- [x] **Step 5:** `lib/contract.ts`: the `ForgeDataParts` map and `ForgeMessage` type from the roadmap
  (`stage`, `file`, `validation`, `checkpoint`, `preview`, `release`, `notice`) typed with
  `UIMessage` from `ai`.
- [x] **Step 6:** `components/forge/status.tsx` renders tone via semantic tokens; the live dot pulses
  opacity only (1.6s, `ease-in-out-strong`), disabled under reduced motion; every badge has a text label.
- [x] **Step 7:** Commit `feat(frontend): status system and draft event contract`.

### Task 5: AI Elements, restyled

**Files:** Create `frontend/components/ai-elements/*` via CLI.

- [x] **Step 1:** `npx shadcn@latest add https://registry.ai-sdk.dev/<name>.json` for: `conversation`,
  `message`, `prompt-input`, `plan`, `task`, `tool`, `confirmation`, `code-block`, `file-tree`,
  `web-preview`, `terminal`, `test-results`, `context`.
- [x] **Step 2:** Review every file: replace raw palette classes with semantic tokens and status
  tones, remove gradients/glows/sparkle icons, align motion with Task 3 rules, keep API unchanged
  so upstream updates stay mergeable.
- [x] **Step 3:** Typecheck, lint and build pass. Commit `feat(frontend): add AI Elements restyled to the design system`.

### Task 6: Fixtures and forge components

**Files:** Create `frontend/lib/fixtures.ts`, `frontend/components/brand-mark.tsx` (under `forge/`),
`frontend/components/forge/stage-list.tsx`

- [x] **Step 1:** `lib/fixtures.ts` exports typed data covering: stage lists for building, review,
  failed and verified runs; a product-contract checkpoint; validation results (passing, failing
  with stderr excerpt); a file tree of a React + FastAPI project including a 120-character path;
  a code sample; preview log lines; a cost ledger.
- [x] **Step 2:** `StageList` renders `ForgeDataParts["stage"][]` with `StatusDot`, label, attempt
  count, detail line; new items enter with `data-motion="rise"` (180ms, 4px, 40ms stagger).
- [x] **Step 3:** `BrandMark`: a geometric anvil/spark mark in `text-brand`, 20px default, `aria-hidden`
  with an accessible wordmark next to it.
- [x] **Step 4:** Commit `feat(frontend): fixtures, brand mark and stage list`.

### Task 7: `/dev/states` reference page and holding page

**Files:** Create `frontend/app/dev/states/page.tsx`, `frontend/components/forge/states/*.tsx`,
`frontend/app/page.tsx`, `frontend/app/not-found.tsx`

- [x] **Step 1:** Sections, each a component in `components/forge/states/`:
  1. Foundations — surfaces, text colours, status tones, type scale, radius, easing demos.
  2. Primitives — buttons (variants, sizes, loading), inputs, select, switch, toggle group, tabs,
     tooltip, dropdown, dialog, toast, alert, empty, skeleton, progress.
  3. Status — every job, stage and release status plus an unknown value.
  4. Build stream — conversation with user prompt, assistant summary, stage list, plan, tasks,
     checkpoint confirmation, validation test results, context/cost.
  5. Code — file tree + code block with a long path.
  6. Preview — web preview frame (empty, starting, failed), terminal logs.
  7. Workspace composition — resizable two-pane studio layout composed from the above with fixtures.
- [x] **Step 2:** Sticky section nav on the left; page `metadata.robots = { index: false }`.
- [x] **Step 3:** `app/page.tsx`: restrained holding page (brand mark, one sentence, links to
  `/dev/states` and the roadmap). No hero gradients, no animation beyond a single 200ms fade-in.
- [x] **Step 4:** Run `npm run lint && npm run typecheck && npm test && npm run build`.
- [x] **Step 5:** Screenshot `/` and `/dev/states` at 1440×900 and 390×844; check focus rings via
  keyboard, check reduced motion with emulation.
- [x] **Step 6:** Commit `feat(frontend): design system reference at /dev/states`.

## Self-review

- Spec coverage: scaffold (T1), tokens/type/motion (T2), primitives (T3), status + contract (T4),
  AI Elements (T5), fixtures + forge components (T6), reference page (T7). Old CSS removal is T1.
- Review focus items map to T4 (unknown status), T2/T7 (reduced motion, focus), T6 (long paths),
  T1/T2 (offline fonts).

## Outcome and deviations

Implemented on `feat/frontend-phase-1-design-system`. Lint, typecheck, 28 tests and the production
build pass from a clean checkout. Verified in a browser at 1440×900 and 390×844, with reduced
motion emulated and keyboard focus checked.

- **Radix instead of Base UI.** AI Elements failed to type-check against the Base UI primitives,
  so the preset is `radix-nova`. Popovers still scale from their trigger via Radix's
  `--radix-*-transform-origin` variables.
- **`context` element removed.** It prices usage from a model catalogue (`tokenlens`) that does
  not know the backend's models. `CostMeter` shows the backend's own cost ledger instead.
- **`shimmer` and `motion` removed.** Shimmering text is an AI cliché; streaming plan titles are
  muted until complete.
- **Upstream AI Elements bugs fixed locally:** hydration mismatch and ref-during-render in
  `code-block`, non-focusable `TaskTrigger`, missing `aria-selected` on file tree items,
  millisecond-only test durations.
- **Added:** `lib/file-tree.ts` (flat paths to a sorted tree, tested), `ProjectFiles`,
  `CheckpointCard`, `ValidationResults`, `FallbackNotice`, and `tests/design-rules.test.ts`,
  which fails CI on any banned pattern from the design brief.
- **Security:** `linkify-it` pinned to a patched version (ReDoS reachable through preview logs);
  `srcDoc` previews get an empty sandbox because they inherit the studio origin.
- **Not verified:** the Docker image (Docker was not running during implementation).

### Review fixes

A whole-branch review found no blockers; its confirmed findings were fixed before hand-off:
folders no longer act as selectable files, icon-only buttons and test statuses have accessible
names, the file tree has one tab stop per item and `role="group"` children, folders that stream
in later start expanded, the highlight cache keys on full source, validation rows have unique
keys, `CostMeter` clamps its ARIA value, remaining transitions respect reduced motion, and
`CheckpointCard` resolves after a decision so it cannot be sent twice.

### Carry into Phase 3

- File tree arrow-key navigation (roving tabindex per the WAI-ARIA tree pattern).

- Real previews: keep `allow-scripts allow-same-origin` only for cross-origin sandbox URLs; the
  browser warns that the combination can escape the sandbox on same-origin content.
- Next.js rewrites do not proxy WebSockets reliably; the collaboration socket needs a direct
  backend URL or a gateway route.
