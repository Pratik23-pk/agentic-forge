"use client";

import { CheckIcon, FileCode2Icon, MessageSquareIcon } from "lucide-react";

import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { Task, TaskContent, TaskTrigger } from "@/components/ai-elements/task";
import { CheckpointCard, gateLabel } from "@/components/forge/checkpoint-card";
import { FallbackNotice } from "@/components/forge/fallback-notice";
import { StageList } from "@/components/forge/stage-list";
import { ReleaseBadge } from "@/components/forge/status";
import { ValidationResults } from "@/components/forge/validation-results";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ForgeMessage } from "@/lib/contract";
import { dataParts, jobPartOf, orderedStages, summaryOf } from "@/lib/studio/messages";

const TERMINAL = new Set(["succeeded", "failed", "blocked"]);

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

interface AssistantMessageProps {
  message: ForgeMessage;
  /** Only the latest build is interactive; earlier versions render as history. */
  isLatest: boolean;
  onApprove: (jobId: string, note: string) => Promise<void>;
  onRequestChanges: (jobId: string, note: string) => Promise<void>;
  onOpenFile: (path: string) => void;
}

export function AssistantMessage({
  message,
  isLatest,
  onApprove,
  onRequestChanges,
  onOpenFile,
}: AssistantMessageProps) {
  const jobId = message.metadata?.jobId ?? "";
  const summary = summaryOf(message);
  const stages = orderedStages(message);
  const checkpoints = dataParts(message, "checkpoint");
  const files = dataParts(message, "file");
  const validation = dataParts(message, "validation");
  const job = jobPartOf(message);
  const terminal = job ? TERMINAL.has(job.status) : false;

  return (
    <Message from="assistant">
      <MessageContent className="w-full gap-4">
        {summary ? <MessageResponse>{summary}</MessageResponse> : null}

        {isLatest && stages.length > 0 ? (
          <div className="rounded-lg border bg-card px-3 py-1.5">
            <StageList stages={stages} />
          </div>
        ) : null}

        {checkpoints.map((checkpoint) =>
          checkpoint.status === "pending" && isLatest ? (
            <CheckpointCard
              key={checkpoint.checkpointId}
              checkpoint={checkpoint}
              onApprove={(note) => onApprove(jobId, note)}
              onRequestChanges={(note) => onRequestChanges(jobId, note)}
            />
          ) : checkpoint.status === "pending" ? null : (
            <p key={checkpoint.checkpointId} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {checkpoint.status === "changes_requested" ? (
                <MessageSquareIcon className="size-3.5" aria-hidden="true" />
              ) : (
                <CheckIcon className="size-3.5 text-success" aria-hidden="true" />
              )}
              {gateLabel(checkpoint.gate)}{" "}
              {checkpoint.status === "changes_requested"
                ? `changes requested${checkpoint.response ? `: ${checkpoint.response}` : ""}`
                : checkpoint.status === "auto_approved"
                  ? "approved automatically"
                  : "approved"}
            </p>
          ),
        )}

        {files.length > 0 ? (
          <Task defaultOpen={false}>
            <TaskTrigger title={`Wrote ${files.length} ${files.length === 1 ? "file" : "files"}`}>
              <button
                type="button"
                className="flex items-center gap-2 rounded-sm text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <FileCode2Icon className="size-3.5" aria-hidden="true" />
                Wrote {files.length} {files.length === 1 ? "file" : "files"}
              </button>
            </TaskTrigger>
            <TaskContent>
              <ul className="flex flex-col">
                {files.map((file) => (
                  <li key={file.path}>
                    <button
                      type="button"
                      disabled={!job?.artifactsReady}
                      onClick={() => onOpenFile(file.path)}
                      title={file.path}
                      className="w-full truncate rounded-sm py-0.5 text-left font-mono text-xs text-muted-foreground transition-colors enabled:hover:text-foreground disabled:cursor-default"
                    >
                      {file.path}
                    </button>
                  </li>
                ))}
              </ul>
            </TaskContent>
          </Task>
        ) : null}

        {isLatest && validation.length > 0 ? <ValidationResults results={validation} /> : null}

        {job?.usedFallback && terminal ? <FallbackNotice /> : null}

        {job?.error && terminal && job.status !== "succeeded" ? (
          <Alert variant="destructive">
            <AlertTitle>The build stopped</AlertTitle>
            <AlertDescription className="break-words">{job.error}</AlertDescription>
          </Alert>
        ) : null}

        {job && terminal ? (
          <div className="flex items-center gap-3 text-xs text-subtle-foreground">
            <ReleaseBadge status={job.releaseStatus} />
            <span className="tabular">{usd.format(job.costUsd)} spent</span>
          </div>
        ) : null}
      </MessageContent>
    </Message>
  );
}
