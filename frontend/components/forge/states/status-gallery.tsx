import { ReleaseBadge, StatusBadge } from "@/components/forge/status";
import { JOB_STATUSES, RELEASE_STATUSES, STAGE_STATUSES } from "@/lib/fixtures";
import { describeRelease } from "@/lib/status";
import { Section, Specimen } from "./section";

export function StatusGallery() {
  return (
    <Section
      id="status"
      title="Status"
      description="Every status the backend can report, plus an unknown value. Colour always travels with a label, and only work in progress pulses."
    >
      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Job">
          <div className="flex flex-wrap gap-2">
            {JOB_STATUSES.map((status) => (
              <StatusBadge key={status} status={status} />
            ))}
            <StatusBadge status="teleporting" />
          </div>
        </Specimen>
        <Specimen label="Stage">
          <div className="flex flex-wrap gap-2">
            {STAGE_STATUSES.map((status) => (
              <StatusBadge key={status} status={status} kind="stage" />
            ))}
          </div>
        </Specimen>
      </div>
      <Specimen label="Release" className="p-0">
        <dl className="divide-y">
          {RELEASE_STATUSES.map((status) => (
            <div key={status} className="grid gap-2 px-5 py-4 sm:grid-cols-[140px_1fr] sm:items-center">
              <dt>
                <ReleaseBadge status={status} />
              </dt>
              <dd className="text-[13px] text-muted-foreground">{describeRelease(status).description}</dd>
            </div>
          ))}
        </dl>
      </Specimen>
    </Section>
  );
}
