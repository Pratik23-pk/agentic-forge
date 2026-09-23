from __future__ import annotations

import json
from textwrap import dedent

from software_developer_agent.models.job_state import WorkerKind
from software_developer_agent.models.request_policy import derive_request_policy


def deterministic_stack_files(
    capability_id: str,
    worker_kind: WorkerKind,
    project_prompt: str,
    project_id: str,
) -> dict[str, str] | None:
    """Return a certified deterministic scaffold when a pack owns the worker output."""

    if worker_kind == WorkerKind.DATABASE:
        return _postgres_database_files(project_prompt)
    if capability_id == "nextjs-fullstack" and worker_kind == WorkerKind.FRONTEND:
        return _nextjs_files(project_prompt, project_id)
    if (
        capability_id in {"react-fastapi", "react-node", "react-vite"}
        and worker_kind == WorkerKind.FRONTEND
    ):
        return _react_vite_files(project_prompt, project_id, capability_id)
    if capability_id in {"react-fastapi", "fastapi-api"} and worker_kind == WorkerKind.BACKEND:
        return _fastapi_files(project_prompt, project_id)
    if capability_id in {"react-node", "node-api"} and worker_kind == WorkerKind.BACKEND:
        return _node_express_files(project_prompt, project_id)
    if capability_id == "python-cli" and worker_kind == WorkerKind.BACKEND:
        return _python_cli_files(project_prompt, project_id)
    return None


def deterministic_validation_commands(
    capability_id: str,
    worker_kind: WorkerKind,
) -> list[str] | None:
    if worker_kind == WorkerKind.DATABASE:
        return ['psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/migrations/001_initial.sql']
    if capability_id == "nextjs-fullstack" and worker_kind == WorkerKind.FRONTEND:
        return ["cd frontend && npm ci && npm test && npm run build"]
    if (
        capability_id in {"react-fastapi", "react-node", "react-vite"}
        and worker_kind == WorkerKind.FRONTEND
    ):
        return ["cd frontend && npm ci && npm test && npm run build"]
    if capability_id in {"react-fastapi", "fastapi-api"} and worker_kind == WorkerKind.BACKEND:
        return ["cd backend && python -m pip install -e '.[test]' && python -m pytest"]
    if capability_id in {"react-node", "node-api"} and worker_kind == WorkerKind.BACKEND:
        return ["cd backend && npm ci && npm test && npm run build"]
    if capability_id == "python-cli" and worker_kind == WorkerKind.BACKEND:
        return ["cd backend && python -m pip install -e '.[test]' && python -m pytest"]
    return None


def trusted_node_package(
    capability_id: str,
    worker_kind: WorkerKind,
) -> dict[str, object] | None:
    """Return the capability pack's certified direct Node dependency policy."""

    files = deterministic_stack_files(
        capability_id,
        worker_kind,
        "Certified capability dependency policy.",
        "capability-policy",
    )
    if not files:
        return None
    package_path = f"{worker_kind.value}/package.json"
    package_text = files.get(package_path)
    if package_text is None:
        return None
    package = json.loads(package_text)
    return package if isinstance(package, dict) else None


def trusted_optional_node_dependencies(
    capability_id: str,
    worker_kind: WorkerKind,
) -> dict[str, dict[str, str]]:
    if worker_kind != WorkerKind.FRONTEND or capability_id not in {
        "react-fastapi",
        "react-node",
        "react-vite",
    }:
        return {}
    return {
        "devDependencies": {
            "@testing-library/dom": "10.4.1",
            "@testing-library/jest-dom": "6.9.1",
            "@testing-library/react": "16.3.2",
            "@testing-library/user-event": "14.6.5",
            "jsdom": "27.4.0",
        }
    }


def _nextjs_files(project_prompt: str, project_id: str) -> dict[str, str]:
    package_name = _slugify(project_id)
    title = _titleize(project_id)
    package = {
        "name": f"{package_name}-nextjs",
        "version": "0.1.0",
        "private": True,
        "scripts": {
            "dev": "next dev",
            "test": "node --test tests/*.test.mjs",
            "build": "next build",
            "start": "next start",
        },
        "dependencies": {
            "next": "16.3.4",
            "react": "19.2.8",
            "react-dom": "19.2.8",
        },
        "devDependencies": {
            "@types/node": "24.3.0",
            "@types/react": "19.1.10",
            "@types/react-dom": "19.1.7",
            "typescript": "5.9.2",
        },
        "engines": {"node": ">=20.9.0"},
    }
    return {
        "frontend/package.json": json.dumps(package, indent=2) + "\n",
        "frontend/tsconfig.json": dedent(
            """
            {
              "compilerOptions": {
                "target": "ES2022",
                "lib": ["dom", "dom.iterable", "esnext"],
                "allowJs": false,
                "skipLibCheck": true,
                "strict": true,
                "noEmit": true,
                "esModuleInterop": true,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": true,
                "isolatedModules": true,
                "jsx": "react-jsx",
                "incremental": true,
                "plugins": [{"name": "next"}],
                "paths": {"@/*": ["./*"]}
              },
              "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
              "exclude": ["node_modules"]
            }
            """
        ).strip()
        + "\n",
        "frontend/next-env.d.ts": (
            '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n'
        ),
        "frontend/next.config.ts": dedent(
            """
            import type { NextConfig } from "next";

            const nextConfig: NextConfig = {
              reactStrictMode: true
            };

            export default nextConfig;
            """
        ).strip()
        + "\n",
        "frontend/app/layout.tsx": dedent(
            f"""
            import type {{ Metadata }} from "next";
            import type {{ ReactNode }} from "react";
            import "./globals.css";

            export const metadata: Metadata = {{
              title: {json.dumps(title)},
              description: "Generated and validated by Agentic Forge"
            }};

            export default function RootLayout({{ children }}: Readonly<{{ children: ReactNode }}>) {{
              return (
                <html lang="en">
                  <body>{{children}}</body>
                </html>
              );
            }}
            """
        ).strip()
        + "\n",
        "frontend/app/page.tsx": dedent(
            f"""
            import {{ projectSummary }} from "@/lib/project";

            export default function Home() {{
              return (
                <main>
                  <section className="card">
                    <p className="eyebrow">Agentic Forge · Next.js</p>
                    <h1>{title}</h1>
                    <p>{{projectSummary}}</p>
                    <a href="/api/health">Verify the server route</a>
                  </section>
                </main>
              );
            }}
            """
        ).strip()
        + "\n",
        "frontend/app/api/health/route.ts": dedent(
            """
            import { NextResponse } from "next/server";

            export function GET() {
              return NextResponse.json({ status: "ok", runtime: "nextjs" });
            }
            """
        ).strip()
        + "\n",
        "frontend/app/globals.css": dedent(
            """
            :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
            * { box-sizing: border-box; }
            body { margin: 0; background: #07101e; color: #edf6ff; }
            main { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
            .card { width: min(720px, 100%); padding: 48px; border: 1px solid #294765;
              border-radius: 20px; background: #0d1b2c; box-shadow: 0 28px 80px #0008; }
            .eyebrow { color: #64c7ff; font-weight: 800; letter-spacing: .12em;
              text-transform: uppercase; }
            h1 { margin: 16px 0; font-size: clamp(2.5rem, 8vw, 5rem); }
            p { color: #a8bdd1; line-height: 1.65; }
            a { display: inline-block; margin-top: 18px; color: #7ee7ca; }
            """
        ).strip()
        + "\n",
        "frontend/lib/project.ts": (
            f"export const projectSummary = {json.dumps(project_prompt.strip())};\n"
        ),
        "frontend/tests/project.test.mjs": dedent(
            """
            import assert from "node:assert/strict";
            import { readFile } from "node:fs/promises";
            import test from "node:test";

            test("the generated project preserves the requested purpose", async () => {
              const source = await readFile(new URL("../lib/project.ts", import.meta.url), "utf8");
              assert.match(source, /projectSummary/);
              assert.ok(source.trim().length > 40);
            });
            """
        ).strip()
        + "\n",
    }


def _node_express_files(project_prompt: str, project_id: str) -> dict[str, str]:
    package_name = _slugify(project_id)
    requires_persistence = _requests_persistence(project_prompt)
    package = {
        "name": f"{package_name}-api",
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "scripts": {
            "dev": "tsx src/main.ts",
            "test": "tsc -p tsconfig.json && node --test tests/*.test.mjs",
            "build": "tsc -p tsconfig.json",
            "start": "node dist/main.js",
        },
        "dependencies": {"express": "5.2.1"},
        "devDependencies": {
            "@types/express": "5.0.3",
            "@types/node": "24.3.0",
            "tsx": "4.20.5",
            "typescript": "5.9.2",
        },
        "engines": {"node": ">=20"},
    }
    if requires_persistence:
        package["dependencies"]["pg"] = "8.16.3"
        package["devDependencies"]["@types/pg"] = "8.15.5"
    return _node_express_source_files(
        package,
        project_prompt,
        project_id,
        requires_persistence=requires_persistence,
    )


def _react_vite_files(
    project_prompt: str,
    project_id: str,
    capability_id: str,
) -> dict[str, str]:
    package_name = _slugify(project_id)
    title = _titleize(project_id)
    has_backend = capability_id in {"react-fastapi", "react-node"}
    package = {
        "name": f"{package_name}-frontend",
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "scripts": {
            "dev": "vite",
            "test": "vitest run",
            "build": "tsc && vite build",
            "preview": "vite preview",
        },
        "dependencies": {
            "react": "19.2.8",
            "react-dom": "19.2.8",
        },
        "devDependencies": {
            "@types/node": "24.3.0",
            "@types/react": "19.1.10",
            "@types/react-dom": "19.1.7",
            "@vitejs/plugin-react": "6.0.3",
            "typescript": "5.9.2",
            "vite": "8.1.0",
            "vitest": "4.1.11",
        },
        "engines": {"node": "^20.19.0 || >=22.12.0"},
    }
    backend_copy = (
        "The API service is available through the configured VITE_API_BASE_URL."
        if has_backend
        else "This standalone application keeps all state in the browser."
    )
    return {
        "frontend/package.json": json.dumps(package, indent=2) + "\n",
        "frontend/tsconfig.json": dedent(
            """
            {
              "compilerOptions": {
                "target": "ES2022",
                "useDefineForClassFields": true,
                "lib": ["ES2022", "DOM", "DOM.Iterable"],
                "allowJs": false,
                "skipLibCheck": true,
                "esModuleInterop": true,
                "allowSyntheticDefaultImports": true,
                "strict": true,
                "forceConsistentCasingInFileNames": true,
                "module": "ESNext",
                "moduleResolution": "Bundler",
                "resolveJsonModule": true,
                "isolatedModules": true,
                "noEmit": true,
                "jsx": "react-jsx",
                "types": ["vitest/globals"]
              },
              "include": ["src"],
              "references": []
            }
            """
        ).strip()
        + "\n",
        "frontend/vite.config.ts": dedent(
            """
            import react from "@vitejs/plugin-react";
            import { defineConfig } from "vite";

            export default defineConfig({
              plugins: [react()],
              server: { host: "127.0.0.1", port: 5173 }
            });
            """
        ).strip()
        + "\n",
        "frontend/index.html": dedent(
            f"""
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <meta name="description" content="Generated and validated by Agentic Forge" />
                <title>{title}</title>
              </head>
              <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
            </html>
            """
        ).strip()
        + "\n",
        "frontend/src/main.tsx": dedent(
            """
            import { StrictMode } from "react";
            import { createRoot } from "react-dom/client";
            import { App } from "./App";
            import "./styles.css";

            const root = document.getElementById("root");
            if (!root) throw new Error("Root element is missing.");
            createRoot(root).render(<StrictMode><App /></StrictMode>);
            """
        ).strip()
        + "\n",
        "frontend/src/vite-env.d.ts": '/// <reference types="vite/client" />\n',
        "frontend/src/project.ts": (
            f"export const projectSummary = {json.dumps(project_prompt.strip())};\n"
            f"export const backendEnabled = {str(has_backend).lower()};\n"
        ),
        "frontend/src/App.tsx": dedent(
            f"""
            import {{ backendEnabled, projectSummary }} from "./project";

            export function App() {{
              return (
                <main>
                  <section className="card" aria-labelledby="project-title">
                    <p className="eyebrow">Agentic Forge · React/Vite</p>
                    <h1 id="project-title">{title}</h1>
                    <p>{{projectSummary}}</p>
                    <div className="status" role="status">
                      <span aria-hidden="true" />
                      {{backendEnabled ? {json.dumps(backend_copy)} : {json.dumps(backend_copy)}}}
                    </div>
                  </section>
                </main>
              );
            }}
            """
        ).strip()
        + "\n",
        "frontend/src/styles.css": dedent(
            """
            :root {
              --background: #07101e;
              --surface: #0d1b2c;
              --text: #edf6ff;
              --muted: #a8bdd1;
              --accent: #64c7ff;
              color-scheme: dark;
              font-family: Inter, system-ui, sans-serif;
            }
            * { box-sizing: border-box; }
            body { margin: 0; background: var(--background); color: var(--text); }
            main { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
            .card { width: min(720px, 100%); padding: clamp(28px, 7vw, 56px);
              border: 1px solid #294765; border-radius: 22px; background: var(--surface);
              box-shadow: 0 28px 80px #0008; }
            .eyebrow { color: var(--accent); font-weight: 800; letter-spacing: .12em;
              text-transform: uppercase; }
            h1 { margin: 16px 0; font-size: clamp(2.5rem, 8vw, 5rem); }
            p { color: var(--muted); line-height: 1.65; }
            .status { display: flex; align-items: center; gap: 10px; margin-top: 24px;
              color: var(--muted); }
            .status span { width: 9px; height: 9px; border-radius: 50%; background: #6de8c7; }
            """
        ).strip()
        + "\n",
        "frontend/src/project.test.ts": dedent(
            """
            import { describe, expect, it } from "vitest";
            import { backendEnabled, projectSummary } from "./project";

            describe("generated project contract", () => {
              it("preserves a non-empty project purpose", () => {
                expect(projectSummary.trim().length).toBeGreaterThan(0);
                expect(typeof backendEnabled).toBe("boolean");
              });
            });
            """
        ).strip()
        + "\n",
    }


def _fastapi_files(project_prompt: str, project_id: str) -> dict[str, str]:
    requires_persistence = _requests_persistence(project_prompt)
    dependencies = ["fastapi==0.115.12", "uvicorn[standard]==0.34.2"]
    if requires_persistence:
        dependencies.extend(["sqlalchemy==2.0.36", "psycopg[binary]==3.2.3"])
    dependency_lines = "\n".join(f'  "{dependency}",' for dependency in dependencies)
    files = {
        "backend/pyproject.toml": dedent(
            f"""
            [project]
            name = "{_slugify(project_id)}-api"
            version = "0.1.0"
            description = {json.dumps(project_prompt.strip())}
            requires-python = ">=3.11"
            dependencies = [
            {dependency_lines}
            ]

            [project.optional-dependencies]
            test = [
              "httpx==0.28.1",
              "pytest==8.3.5"
            ]

            [build-system]
            requires = ["hatchling==1.27.0"]
            build-backend = "hatchling.build"

            [tool.hatch.build.targets.wheel]
            packages = ["src/app"]

            [tool.pytest.ini_options]
            testpaths = ["tests"]
            pythonpath = ["src"]
            """
        ).strip()
        + "\n",
        "backend/src/app/__init__.py": "",
        "backend/src/app/main.py": _fastapi_main(
            project_prompt,
            project_id,
            requires_persistence=requires_persistence,
        ),
        "backend/tests/test_app.py": dedent(
            """
            from fastapi.testclient import TestClient

            from app.main import app


            client = TestClient(app)


            def test_health_reports_fastapi_runtime() -> None:
                response = client.get("/health")
                assert response.status_code == 200
                assert response.json() == {"status": "ok", "runtime": "fastapi"}


            def test_project_workflow_returns_generated_purpose() -> None:
                response = client.get("/api/project")
                assert response.status_code == 200
                assert response.json()["purpose"]
            """
        ).strip()
        + "\n",
    }
    if requires_persistence:
        files["backend/.env.example"] = (
            "DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/app\n"
        )
    return files


def _fastapi_main(
    project_prompt: str,
    project_id: str,
    *,
    requires_persistence: bool,
) -> str:
    imports = [
        "from fastapi import FastAPI, HTTPException",
        "from fastapi.middleware.cors import CORSMiddleware",
    ]
    configuration = ""
    records_route: list[str] = []
    if requires_persistence:
        imports.extend(
            [
                "from os import getenv",
                "from sqlalchemy import create_engine, text",
                "from sqlalchemy.engine import Engine",
            ]
        )
        configuration = (
            'DATABASE_URL = getenv("DATABASE_URL")\n'
            "database_engine: Engine | None = (\n"
            "    create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None\n"
            ")\n"
        )
        records_route = [
            '    @app.get("/api/records")',
            "    def records() -> list[dict[str, object]]:",
            "        if database_engine is None:",
            '            raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")',
            "        with database_engine.connect() as connection:",
            "            rows = connection.execute(",
            '                text("select record_id, kind, title, status from public.app_records")',
            "            ).mappings()",
            "            return [dict(row) for row in rows]",
            "",
        ]
    lines = [
        "from __future__ import annotations",
        "",
        *imports,
        "",
        f"PROJECT_NAME = {json.dumps(_titleize(project_id))}",
        f"PROJECT_PURPOSE = {json.dumps(project_prompt.strip())}",
        *(configuration.rstrip().splitlines() if configuration else []),
        "",
        "",
        "def create_app() -> FastAPI:",
        "    app = FastAPI(title=PROJECT_NAME)",
        "    app.add_middleware(",
        "        CORSMiddleware,",
        '        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],',
        "        allow_credentials=False,",
        '        allow_methods=["GET"],',
        '        allow_headers=["Content-Type"],',
        "    )",
        "",
        '    @app.get("/health")',
        "    def health() -> dict[str, str]:",
        '        return {"status": "ok", "runtime": "fastapi"}',
        "",
        '    @app.get("/api/project")',
        "    def project() -> dict[str, str]:",
        '        return {"name": PROJECT_NAME, "purpose": PROJECT_PURPOSE}',
        "",
        *records_route,
        "    return app",
        "",
        "",
        "app = create_app()",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _postgres_database_files(project_prompt: str) -> dict[str, str]:
    lowered = project_prompt.lower()
    policy = derive_request_policy(project_prompt)
    uses_supabase = policy.allows("cloud") and "supabase" in lowered
    if uses_supabase:
        identity_schema = dedent(
            """
            create table if not exists public.profiles (
              user_id uuid primary key references auth.users(id) on delete cascade,
              display_name text not null default '',
              created_at timestamptz not null default now()
            );

            alter table public.profiles enable row level security;
            create policy "profiles are readable by their owner"
              on public.profiles for select using (auth.uid() = user_id);
            create policy "profiles are editable by their owner"
              on public.profiles for update using (auth.uid() = user_id);
            """
        ).strip()
        storage_schema = (
            dedent(
                """

                insert into storage.buckets (id, name, public)
                values ('project-assets', 'project-assets', false)
                on conflict (id) do nothing;

                create policy "users manage their own project assets"
                  on storage.objects for all
                  using (bucket_id = 'project-assets' and auth.uid()::text = (storage.foldername(name))[1])
                  with check (bucket_id = 'project-assets' and auth.uid()::text = (storage.foldername(name))[1]);
                """
            ).rstrip()
            if any(
                term in lowered
                for term in ("file upload", "image upload", "media upload", "video upload")
            )
            else ""
        )
    else:
        identity_schema = ""
        storage_schema = ""
    migration = (
        dedent(
            f"""
        create extension if not exists pgcrypto;

        create table if not exists public.app_records (
          record_id uuid primary key default gen_random_uuid(),
          kind text not null,
          title text not null,
          status text not null default 'active',
          payload jsonb not null default '{{}}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create index if not exists app_records_kind_status_idx
          on public.app_records (kind, status);

        {identity_schema}
        {storage_schema}
        """
        ).strip()
        + "\n"
    )
    return {
        "database/migrations/001_initial.sql": migration,
        "database/.env.example": (
            "DATABASE_URL=\n" + ("SUPABASE_URL=\nSUPABASE_ANON_KEY=\n" if uses_supabase else "")
        ),
    }


def _node_express_source_files(
    package: dict[str, object],
    project_prompt: str,
    project_id: str,
    *,
    requires_persistence: bool,
) -> dict[str, str]:
    app_source = dedent(
        f"""
        import express from "express";

        export const projectPrompt = {json.dumps(project_prompt.strip())};

        export function createApp() {{
          const app = express();
          app.disable("x-powered-by");
          app.use(express.json({{ limit: "1mb" }}));
          app.get("/health", (_request, response) => {{
            response.json({{ status: "ok", runtime: "node" }});
          }});
          app.get("/api/project", (_request, response) => {{
            response.json({{ name: {json.dumps(project_id)}, prompt: projectPrompt }});
          }});
          return app;
        }}
        """
    ).strip()
    if requires_persistence:
        app_source = 'import { Pool } from "pg";\n' + app_source
        app_source = app_source.replace(
            f"export const projectPrompt = {json.dumps(project_prompt.strip())};",
            (
                f"export const projectPrompt = {json.dumps(project_prompt.strip())};\n"
                "export const databaseUrl = process.env.DATABASE_URL;\n"
                "export const databasePool = databaseUrl\n"
                "  ? new Pool({ connectionString: databaseUrl })\n"
                "  : null;"
            ),
        )
        app_source = app_source.replace(
            "  return app;",
            dedent(
                """
                  app.get("/api/records", async (_request, response, next) => {
                    if (!databasePool) {
                      response.status(503).json({ error: "DATABASE_URL is not configured" });
                      return;
                    }
                    try {
                      const result = await databasePool.query(
                        "select record_id, kind, title, status from public.app_records"
                      );
                      response.json({ items: result.rows });
                    } catch (error) {
                      next(error);
                    }
                  });
                  return app;
                """
            ).strip("\n"),
        )
    files = {
        "backend/package.json": json.dumps(package, indent=2) + "\n",
        "backend/tsconfig.json": dedent(
            """
            {
              "compilerOptions": {
                "target": "ES2022",
                "module": "NodeNext",
                "moduleResolution": "NodeNext",
                "rootDir": "src",
                "outDir": "dist",
                "strict": true,
                "esModuleInterop": true,
                "skipLibCheck": true,
                "forceConsistentCasingInFileNames": true
              },
              "include": ["src/**/*.ts"]
            }
            """
        ).strip()
        + "\n",
        "backend/src/app.ts": app_source + "\n",
        "backend/src/main.ts": dedent(
            """
            import { createApp } from "./app.js";

            const port = Number.parseInt(process.env.PORT ?? "8000", 10);
            const server = createApp().listen(port, "127.0.0.1", () => {
              console.log(`Node API listening on http://127.0.0.1:${port}`);
            });

            function shutdown() {
              server.close(() => process.exit(0));
            }

            process.on("SIGINT", shutdown);
            process.on("SIGTERM", shutdown);
            """
        ).strip()
        + "\n",
        "backend/tests/app.test.mjs": dedent(
            """
            import assert from "node:assert/strict";
            import test from "node:test";
            import { createApp } from "../dist/app.js";

            test("health endpoint reports the Node runtime", async () => {
              const server = createApp().listen(0, "127.0.0.1");
              await new Promise((resolve) => server.once("listening", resolve));
              const address = server.address();
              assert.ok(address && typeof address === "object");
              const response = await fetch(`http://127.0.0.1:${address.port}/health`);
              assert.equal(response.status, 200);
              assert.deepEqual(await response.json(), { status: "ok", runtime: "node" });
              await new Promise((resolve, reject) =>
                server.close((error) => error ? reject(error) : resolve())
              );
            });
            """
        ).strip()
        + "\n",
    }
    if requires_persistence:
        files["backend/.env.example"] = (
            "DATABASE_URL=postgresql://user:password@localhost:5432/app\n"
        )
    return files


def _requests_persistence(project_prompt: str) -> bool:
    policy = derive_request_policy(project_prompt)
    return policy.allows("database") or policy.allows("persistence")


def _python_cli_files(project_prompt: str, project_id: str) -> dict[str, str]:
    package_name = _slugify(project_id).replace("-", "_")
    return {
        "backend/pyproject.toml": dedent(
            f"""
            [project]
            name = "{_slugify(project_id)}"
            version = "0.1.0"
            description = {json.dumps(project_prompt.strip())}
            requires-python = ">=3.11"
            dependencies = []

            [project.optional-dependencies]
            test = ["pytest==8.3.5"]

            [project.scripts]
            {package_name} = "{package_name}.cli:main"

            [build-system]
            requires = ["hatchling==1.27.0"]
            build-backend = "hatchling.build"

            [tool.pytest.ini_options]
            testpaths = ["tests"]
            pythonpath = ["src"]
            """
        ).strip()
        + "\n",
        f"backend/src/{package_name}/__init__.py": "",
        f"backend/src/{package_name}/cli.py": dedent(
            f"""
            from __future__ import annotations

            import argparse

            PROJECT_PURPOSE = {json.dumps(project_prompt.strip())}


            def build_parser() -> argparse.ArgumentParser:
                parser = argparse.ArgumentParser(prog="{_slugify(project_id)}")
                parser.add_argument("--describe", action="store_true", help="Print the project purpose.")
                return parser


            def main(argv: list[str] | None = None) -> int:
                arguments = build_parser().parse_args(argv)
                if arguments.describe:
                    print(PROJECT_PURPOSE)
                else:
                    print("{_titleize(project_id)} is ready.")
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
            """
        ).strip()
        + "\n",
        "backend/tests/test_cli.py": dedent(
            f"""
            from {package_name}.cli import main


            def test_describe_prints_the_project_purpose(capsys) -> None:
                assert main(["--describe"]) == 0
                assert capsys.readouterr().out.strip()
            """
        ).strip()
        + "\n",
    }


def _slugify(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in normalized.split("-") if part) or "generated-project"


def _titleize(value: str) -> str:
    return " ".join(part.capitalize() for part in _slugify(value).split("-"))
