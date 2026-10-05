import type { CSSProperties } from "react";

import { StatusDot } from "@/components/forge/status";
import { STAGE_LABELS, type StagePart } from "@/lib/contract";
import { describeStageStatus } from "@/lib/status";
import { cn } from "@/lib/utils";

interface StageListProps {
  stages: StagePart[];
  className?: string;
}

/**
 * Build stages in pipeline order. Each row keys on its stage id, so when a
 * streamed update changes a stage the row updates in place; only genuinely
 * new rows play the entrance.
 */
export function StageList({ stages, className }: StageListProps) {
  return (
    <ol className={cn("flex flex-col", className)} aria-label="Build stages">
      {stages.map((stage, index) => {
        const status = describeStageStatus(stage.status);
        return (
          <li
            key={stage.stage}
            data-motion="rise"
            style={{ "--i": index } as CSSProperties}
            className="stagger grid animate-rise grid-cols-[12px_1fr_auto] items-baseline gap-x-2.5 py-1.5"
          >
            <StatusDot tone={status.tone} live={status.live} className="translate-y-[-1px]" />
            <div className="min-w-0">
              <span
                className={cn(
                  "text-[13px]",
                  stage.status === "queued" ? "text-subtle-foreground" : "text-foreground",
                )}
              >
                {STAGE_LABELS[stage.stage]}
              </span>
              {stage.detail ? (
                <p className="truncate text-xs text-muted-foreground">{stage.detail}</p>
              ) : null}
            </div>
            <span className="tabular text-xs text-subtle-foreground">
              {stage.attempt && stage.attempt > 1 ? `Attempt ${stage.attempt} · ` : ""}
              {status.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
