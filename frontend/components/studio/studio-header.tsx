"use client";

import { DownloadIcon, PlusIcon } from "lucide-react";

import { Wordmark } from "@/components/forge/brand-mark";
import { StatusBadge } from "@/components/forge/status";
import { Button } from "@/components/ui/button";
import type { JobPart } from "@/lib/contract";
import { downloadUrl } from "@/lib/studio/api";
import { PublishDialog } from "./publish-dialog";

interface StudioHeaderProps {
  projectName: string;
  jobId: string | undefined;
  job: JobPart | undefined;
}

export function StudioHeader({ projectName, jobId, job }: StudioHeaderProps) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b px-3">
      {/* Full loads to /studio reset the chat; see the New button below. */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a href="/studio" className="rounded-md" aria-label="All projects">
        <Wordmark />
      </a>
      <span className="text-border-strong" aria-hidden="true">
        /
      </span>
      <h1 className="min-w-0 flex-1 truncate text-[13px] font-normal" title={projectName}>
        {projectName}
      </h1>
      {job ? <StatusBadge status={job.status} /> : null}
      <div className="flex items-center gap-1">
        <Button asChild variant="ghost" size="sm">
          {/* A full load on purpose: a new project must start with a fresh chat. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/studio">
            <PlusIcon data-icon="inline-start" />
            New
          </a>
        </Button>
        {jobId && job?.artifactsReady ? (
          <Button asChild variant="ghost" size="sm">
            <a href={downloadUrl(jobId)} download>
              <DownloadIcon data-icon="inline-start" />
              ZIP
            </a>
          </Button>
        ) : (
          <Button variant="ghost" size="sm" disabled>
            <DownloadIcon data-icon="inline-start" />
            ZIP
          </Button>
        )}
        <PublishDialog jobId={jobId} job={job} />
      </div>
    </header>
  );
}
