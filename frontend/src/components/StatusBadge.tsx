import { AlertCircle, CheckCircle2, Clock, RefreshCw, ShieldAlert } from "lucide-react";

import type { JobStatus, TaskStatus } from "../lib/api";

type Status = JobStatus | TaskStatus | string;

const statusIcon = {
  succeeded: CheckCircle2,
  failed: AlertCircle,
  blocked: ShieldAlert,
  retrying: RefreshCw,
  running: RefreshCw,
  awaiting_human_feedback: Clock,
  evaluating: RefreshCw,
  pending: Clock,
  skipped: Clock
};

export function StatusBadge({ status }: { status: Status }) {
  const Icon = statusIcon[status as keyof typeof statusIcon] ?? Clock;
  return (
    <span className={`status-badge status-${status}`}>
      <Icon size={14} aria-hidden="true" />
      {status}
    </span>
  );
}
