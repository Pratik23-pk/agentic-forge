import { CostMeter } from "@/components/forge/cost-meter";
import { StageList } from "@/components/forge/stage-list";
import { ReleaseBadge } from "@/components/forge/status";
import { ValidationResults } from "@/components/forge/validation-results";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { JobPart, StagePart, StageId, ValidationPart } from "@/lib/contract";
import { describeRelease } from "@/lib/status";

const ORDER: StageId[] = ["plan", "design", "database", "backend", "frontend", "validate", "evaluate", "release"];

interface ActivityTabProps {
  job: JobPart | undefined;
  stages: StagePart[];
  validation: ValidationPart[];
}

export function ActivityTab({ job, stages, validation }: ActivityTabProps) {
  const ordered = [...stages].sort((a, b) => ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage));

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8 p-6">
      <section className="flex flex-col gap-3" aria-labelledby="activity-stages">
        <h2 id="activity-stages" className="text-xs font-normal text-subtle-foreground">
          Pipeline
        </h2>
        <div className="rounded-xl border bg-card px-4 py-2">
          <StageList stages={ordered} />
        </div>
      </section>

      {job ? (
        <section className="flex flex-col gap-3" aria-labelledby="activity-release">
          <h2 id="activity-release" className="text-xs font-normal text-subtle-foreground">
            Release
          </h2>
          <div className="flex flex-col gap-4 rounded-xl border bg-card p-4">
            <div className="flex items-start gap-3">
              <ReleaseBadge status={job.releaseStatus} />
              <p className="text-[13px] text-muted-foreground">{describeRelease(job.releaseStatus).description}</p>
            </div>
            <CostMeter spentUsd={job.costUsd} budgetUsd={job.budgetUsd} />
          </div>
          {job.error ? (
            <Alert variant="destructive">
              <AlertTitle>Last error</AlertTitle>
              <AlertDescription className="font-mono text-xs break-words">{job.error}</AlertDescription>
            </Alert>
          ) : null}
        </section>
      ) : null}

      <section className="flex flex-col gap-3" aria-labelledby="activity-validation">
        <h2 id="activity-validation" className="text-xs font-normal text-subtle-foreground">
          Validation
        </h2>
        {validation.length > 0 ? (
          <ValidationResults results={validation} />
        ) : (
          <p className="text-[13px] text-muted-foreground">
            Install, test and build results appear here after the sandbox runs them.
          </p>
        )}
      </section>
    </div>
  );
}
