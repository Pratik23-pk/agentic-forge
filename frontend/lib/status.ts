/**
 * Maps backend status strings to presentation. Pure and total: any string,
 * including values the backend adds later, resolves to something renderable.
 */

export type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

export interface StatusDescription {
  label: string;
  tone: Tone;
  /** True while work is actively happening; drives the live indicator. */
  live: boolean;
}

export interface ReleaseDescription {
  label: string;
  tone: Tone;
  description: string;
}

const UNKNOWN: StatusDescription = { label: "Unknown", tone: "neutral", live: false };

const JOB_STATUS: Record<string, StatusDescription> = {
  pending: { label: "Queued", tone: "neutral", live: false },
  running: { label: "Building", tone: "brand", live: true },
  evaluating: { label: "Evaluating", tone: "brand", live: true },
  retrying: { label: "Repairing", tone: "brand", live: true },
  awaiting_human_feedback: { label: "Needs review", tone: "warning", live: false },
  succeeded: { label: "Succeeded", tone: "success", live: false },
  failed: { label: "Failed", tone: "danger", live: false },
  blocked: { label: "Blocked", tone: "danger", live: false },
};

const STAGE_STATUS: Record<string, StatusDescription> = {
  queued: { label: "Queued", tone: "neutral", live: false },
  running: { label: "Running", tone: "brand", live: true },
  review: { label: "Review", tone: "warning", live: false },
  done: { label: "Done", tone: "success", live: false },
  failed: { label: "Failed", tone: "danger", live: false },
};

const RELEASE_STATUS: Record<string, ReleaseDescription> = {
  pending: {
    label: "Pending",
    tone: "neutral",
    description: "The build has not produced a release candidate yet.",
  },
  verified: {
    label: "Verified",
    tone: "success",
    description: "Passed validation. Preview, download and publication are available.",
  },
  provisional: {
    label: "Provisional",
    tone: "warning",
    description: "Runnable with validation warnings. Preview and download are available.",
  },
  quarantined: {
    label: "Quarantined",
    tone: "danger",
    description: "Blocking security findings. Isolated preview and download only; publication is locked.",
  },
};

function lookup<T>(table: Record<string, T>, key: string, fallback: T): T {
  return Object.hasOwn(table, key) ? table[key] : fallback;
}

export function describeJobStatus(status: string): StatusDescription {
  return lookup(JOB_STATUS, status, UNKNOWN);
}

export function describeStageStatus(status: string): StatusDescription {
  return lookup(STAGE_STATUS, status, UNKNOWN);
}

export function describeRelease(status: string): ReleaseDescription {
  return lookup(RELEASE_STATUS, status, {
    label: "Unknown",
    tone: "neutral",
    description: "The release state could not be determined.",
  });
}
