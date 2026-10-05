# Frontend Roadmap

The studio is being rebuilt from a single 1,800-line Vite component with 4,000 lines of hand-written
CSS into a Next.js application with a real design system, a streaming AI SDK integration and a
Studio gateway that owns auth and translates backend job state into a UI message stream.

```
Browser (Next.js 16 + shadcn/ui + AI Elements, useChat)
   │  one SSE stream per build (AI SDK UI message stream, data-* parts)
   ▼
Next.js route handlers — "Studio gateway"
   │  auth, stream translation, rate limits
   ▼
Python FastAPI + LangGraph (unchanged at first)
```

| Phase | Outcome | Depends on backend? |
| --- | --- | --- |
| 1. Design system | Next.js scaffold, dark theme, motion system, primitives, AI Elements restyled, `/dev/states` | No |
| 0. Contract | OpenAPI-generated types, event contract (`data-*` parts), recorded fixtures, mock transport | Response models on FastAPI routes |
| 2. Gateway | `POST /api/chat` translating job polling into a UI message stream, resume, approvals | No (adapter polls existing API) |
| 3. Studio | Chat, preview, code editor, activity, publish — rebuilt on the gateway | No |
| 4. Projects | Auth, projects dashboard, follow-up edits, version timeline | Yes: revision endpoint, user scoping |
| 5. Landing + polish | SSR landing page, accessibility, performance | No |
| 6. Quality | Playwright E2E, visual regression, Sentry, PostHog, build metrics | No |

Phase 1 is done first because every later phase builds on its tokens and components. The minimum
of Phase 0 that Phase 1 needs (the scaffold, tooling and a first draft of the event contract types
used by fixtures) is included in Phase 1.

## Asks for the backend (in priority order)

1. Pydantic response models on every route so OpenAPI carries response shapes.
2. A slim job summary endpoint without file contents or raw model output.
3. An event stream matching `frontend/lib/contract.ts`.
4. A follow-up edit endpoint that patches an existing project.
5. User scoping on jobs and projects.
6. Asynchronous preview start (202 + status).

## Branch state

While Phases 1–3 are in progress the studio on this branch is replaced by the design-system
reference at `/dev/states`. The working studio remains on `main` until Phase 3 lands.
