"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { Wordmark } from "@/components/forge/brand-mark";
import { StatusBadge } from "@/components/forge/status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { listJobs, queryKeys } from "@/lib/studio/api";
import { formatRelativeTime } from "@/lib/studio/format";

export const STACKS = [
  ["auto", "Detect stack"],
  ["nextjs-fullstack", "Next.js full-stack"],
  ["react-fastapi", "React + FastAPI"],
  ["react-node", "React + Express"],
  ["react-vite", "React (Vite)"],
  ["fastapi-api", "FastAPI API"],
  ["node-api", "Express API"],
  ["python-cli", "Python CLI"],
] as const;

const SUGGESTIONS = [
  "A habit tracker where I add habits and tick them off each day",
  "A booking page for a small yoga studio with class schedules",
  "An internal dashboard that lists support tickets by priority",
];

export interface NewProjectRequest {
  prompt: string;
  projectName: string;
  capabilityId: string;
}

interface NewProjectProps {
  sending: boolean;
  error: Error | undefined;
  onStart: (request: NewProjectRequest) => void;
}

function RecentProjects() {
  const { data, isPending, isError } = useQuery({ queryKey: queryKeys.jobs, queryFn: listJobs });

  if (isPending) {
    return (
      <div className="flex flex-col gap-2" aria-hidden="true">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-11 w-full" />
        ))}
      </div>
    );
  }
  if (isError) {
    return <p className="text-[13px] text-muted-foreground">Recent projects are unavailable while the backend is offline.</p>;
  }
  if (!data.length) {
    return <p className="text-[13px] text-muted-foreground">Projects you build appear here.</p>;
  }

  return (
    <ul className="flex flex-col divide-y rounded-xl border bg-card">
      {data.slice(0, 8).map((job) => (
        <li key={job.job_id}>
          <Link
            href={`/studio/${job.job_id}`}
            className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-0.5 px-4 py-3 transition-colors duration-150 hover:bg-accent/50 sm:grid-cols-[1fr_auto_auto]"
          >
            <span className="min-w-0">
              <span className="block truncate text-[13px]">{job.request.project_id}</span>
              <span className="block truncate text-xs text-subtle-foreground">
                {(job.request.metadata?.display_prompt as string | undefined) ?? job.request.prompt}
              </span>
            </span>
            <StatusBadge status={job.status} />
            <span className="tabular hidden text-xs text-subtle-foreground sm:block">
              {formatRelativeTime(job.updated_at)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function NewProject({ sending, error, onStart }: NewProjectProps) {
  const [prompt, setPrompt] = useState("");
  const [projectName, setProjectName] = useState("");
  const [capabilityId, setCapabilityId] = useState<string>("auto");
  const canStart = prompt.trim().length > 0 && !sending;

  return (
    <main className="flex min-h-dvh flex-col">
      <header className="flex h-12 shrink-0 items-center border-b px-4">
        <Link href="/studio" className="rounded-md" aria-label="Studio home">
          <Wordmark />
        </Link>
      </header>

      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-12 px-6 pt-[12vh] pb-16">
        <div className="flex animate-fade flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.02em]">What should we build?</h1>
            <p className="text-[15px] leading-relaxed text-muted-foreground">
              Describe the product. Agentic Forge plans it, writes the frontend and backend, tests the
              result in a sandbox, and hands you a runnable project.
            </p>
          </div>

          <PromptInput
            onSubmit={() => {
              if (!canStart) return;
              onStart({
                prompt: prompt.trim(),
                projectName: projectName.trim(),
                capabilityId: capabilityId === "auto" ? "" : capabilityId,
              });
            }}
          >
            <PromptInputBody>
              <PromptInputTextarea
                autoFocus
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="A customer portal where members manage their plan and see upcoming deliveries"
                className="min-h-24 text-sm"
              />
            </PromptInputBody>
            <PromptInputFooter className="gap-2">
              <PromptInputTools className="min-w-0 gap-2">
                <Input
                  aria-label="Project name"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="Project name (optional)"
                  maxLength={80}
                  className="h-7 w-48 min-w-0 text-xs md:text-xs"
                />
                <Select value={capabilityId} onValueChange={setCapabilityId}>
                  <SelectTrigger size="sm" aria-label="Stack" className="h-7 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {STACKS.map(([value, label]) => (
                        <SelectItem key={value} value={value} className="text-xs">
                          {label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </PromptInputTools>
              <PromptInputSubmit
                disabled={!canStart}
                status={sending ? "submitted" : "ready"}
                aria-label="Start building"
              />
            </PromptInputFooter>
          </PromptInput>

          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((suggestion) => (
              <Button
                key={suggestion}
                variant="outline"
                size="sm"
                className="h-auto max-w-full rounded-full py-1 text-left text-xs font-normal whitespace-normal text-muted-foreground"
                onClick={() => setPrompt(suggestion)}
              >
                {suggestion}
              </Button>
            ))}
          </div>

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>The build could not start</AlertTitle>
              <AlertDescription className="break-words">{error.message}</AlertDescription>
            </Alert>
          ) : null}
        </div>

        <section aria-labelledby="recent-projects" className="flex flex-col gap-3">
          <h2 id="recent-projects" className="text-xs font-normal text-subtle-foreground">
            Recent projects
          </h2>
          <RecentProjects />
        </section>
      </div>
    </main>
  );
}
