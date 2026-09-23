import { Activity, CheckCircle2, RefreshCw, ShieldAlert, XCircle } from "lucide-react";

import type { Metrics } from "../lib/api";

interface MetricStripProps {
  metrics: Metrics | null;
}

export function MetricStrip({ metrics }: MetricStripProps) {
  const items = [
    { label: "Submitted", value: metrics?.jobs_submitted ?? 0, icon: Activity },
    { label: "Succeeded", value: metrics?.jobs_succeeded ?? 0, icon: CheckCircle2 },
    { label: "Failed", value: metrics?.jobs_failed ?? 0, icon: XCircle },
    { label: "Retries", value: metrics?.retries_scheduled ?? 0, icon: RefreshCw },
    { label: "Blocks", value: metrics?.guardrail_blocks ?? 0, icon: ShieldAlert }
  ];

  return (
    <section className="metric-strip" aria-label="Runtime metrics">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div className="metric" key={item.label}>
            <Icon size={18} aria-hidden="true" />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        );
      })}
    </section>
  );
}
