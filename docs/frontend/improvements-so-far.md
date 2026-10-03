# Improvements So Far

Everything changed on the frontend side, in the order it was done. Branches:
`feat/frontend-phase-1-design-system` (Phase 1) and `feat/frontend-phase-2-3-studio` (Phases 2–3,
stacked on Phase 1). Nothing is merged into `main` yet; the original studio still lives there.

## 0. Research and documentation

1. **Full codebase review**: frontend, AI pipeline, API/security/sandbox, validation and tests.
   Backend tests were run (363 passed); frontend and backend quality measured (lint, types, coverage).
2. **Backend architecture review for the founder**: 24 problems with file and line, impact, fix and an
   order of work (`docs/architecture-review.md`).
3. **Frontend roadmap** with phases and the list of backend requests (`docs/frontend/roadmap.md`).
4. **Implementation plans** for each phase (`docs/frontend/phase-1-design-system.md`,
   `docs/frontend/phase-2-3-studio.md`).

## 1. Phase 1 — new foundation and design system

5. **Replaced the old frontend entirely.** Removed one 1,794-line component, 4,000 lines of
   hand-written CSS and the dead components. Rebuilt on Next.js 16, React 19, strict TypeScript,
   Tailwind CSS 4, shadcn/ui and Vercel AI Elements.
6. **Dark, restrained design system**: neutral surfaces with hairline borders, one ember accent used
   only for brand, focus and live work, muted status colours that always come with a label, Geist fonts.
7. **Motion system following Emil Kowalski's rules**: strong ease-out curves, 150 ms presses that
   scale to 0.97, popovers that grow from their trigger, nothing over 300 ms in the product, full
   reduced-motion support.
8. **"No AI clichés" enforced by a test**: CI fails on gradients, glows, glass blur, `transition-all`,
   `ease-in`, raw palette colours or `scale(0)` entrances.
9. **Status system** that maps every backend status to a label and tone, and never crashes on unknown values.
10. **Design-system reference page** at `/dev/states` showing every component in every state.
11. **Draft streaming contract** (`lib/contract.ts`): the data shapes a build streams to the UI.
12. **Tooling**: ESLint, type-check, Vitest and Testing Library; CI runs lint, types, tests and build.

Bugs fixed in third-party code along the way:

13. AI Elements code blocks broke server rendering (hydration mismatch) and never showed colours.
14. Task toggles were not keyboard-focusable; file tree items lacked selection state for screen readers.
15. Icon-only buttons had no accessible names; test pass/fail was shown by colour alone.
16. A dependency of the log viewer had a denial-of-service advisory; pinned to the patched version.
17. Preview mock iframes could escape their sandbox; now fully sandboxed.

## 2. Phase 2 — streaming gateway (new UI talks to the real backend)

18. **`POST /api/chat`** starts a build and streams it to the browser as it happens (AI SDK UI message
    stream). The browser no longer polls the backend.
19. **`GET /api/chat/<job>/stream`** re-attaches to a build after a reload or an approval.
20. **Translator** turns raw backend job data into clear parts: summary, ordered stages, approval
    gates, files written, validation results, outcome and cost. Tested against real recorded jobs.
21. **Reload-safe**: reloading mid-build shows current progress with no duplicates.
22. **Race fixed**: a fast build could reach its next approval before the page reconnected; the
    gateway now always sends the latest state.
23. **Readable backend errors**: policy rejections and outages show a clear message, not raw JSON.
24. **Preview start timeout raised** from 30 s to 10 minutes so first starts are not cut off.

## 3. Phase 3 — the working studio

25. **New project screen** (`/studio`): prompt, optional name, stack picker, example prompts, recent projects.
26. **Project workspace** (`/studio/<id>`): chat on the left, tabs on the right; the URL follows the
    latest version and can be shared or reloaded.
27. **Approval cards**: approve or request changes inline; decisions cannot be sent twice.
28. **Preview tab**: auto-starts when files are ready, start timer, desktop/tablet/phone sizes, reload,
    open in new tab, logs, stop, quarantine banner, readable failure messages with details on demand.
29. **Code tab**: real code editor (CodeMirror) with syntax colours, ⌘S save, a warning before
    discarding unsaved edits, and a merge dialog if someone else changed the file.
30. **Activity tab**: pipeline, release state, cost against budget, validation results, last error.
31. **Header actions**: download ZIP, publish to GitHub (enabled only when the build is verified and
    GitHub is configured, with the reason shown otherwise).
32. **Honest labelling** of backend limits: template fallback warning, "each change builds a new
    version", locked composer while a build runs or awaits approval.
33. **Follow-up versions**: asking for a change builds a new version from the original request plus
    every change so far.

## 4. Fixes from reviews and browser testing

34. Clicking a folder no longer opens the wrong file; the file tree has proper keyboard and screen-reader support.
35. Folders that appear during a build start expanded; your collapses are remembered.
36. Code highlighting no longer reuses another file's colours.
37. Long npm and Docker errors become one readable line, with full details on demand.
38. Publish is only a primary button when publishing is possible.
39. Docker deployment: the runtime image now knows where the backend is.
40. Keystrokes typed while a save is in progress are kept.
41. Opening a file from the chat respects the unsaved-changes warning.
42. Failed sends offer "Try again"; "Reconnect" only appears for a live build.
43. Files and preview refresh when a build rewrites them.
44. The stream no longer leaks event listeners on long builds.
45. Follow-up prompts no longer nest inside each other.
46. Files starting with a byte-order mark no longer always report a save conflict.

## 5. Verification

- 87 frontend tests, lint, strict type-check and production build pass.
- Checked in a real browser against the backend in test mode: new project, both approvals, reload
  mid-approval, preview failure, edit and save, unsaved-changes guard, follow-up version.
- Not yet verified: a build with a real OpenAI key, and the Docker image.
