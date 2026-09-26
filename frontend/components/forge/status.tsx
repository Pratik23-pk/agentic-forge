import { cva } from "class-variance-authority";

import { Badge } from "@/components/ui/badge";
import {
  describeJobStatus,
  describeRelease,
  describeStageStatus,
  type Tone,
} from "@/lib/status";
import { cn } from "@/lib/utils";

const dotVariants = cva("inline-block size-1.5 shrink-0 rounded-full", {
  variants: {
    tone: {
      neutral: "bg-subtle-foreground",
      brand: "bg-brand",
      success: "bg-success",
      warning: "bg-warning",
      danger: "bg-danger",
      info: "bg-info",
    },
    live: {
      true: "animate-live",
      false: "",
    },
  },
  defaultVariants: { tone: "neutral", live: false },
});

const badgeTone: Record<Tone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  brand: "border-brand/20 bg-brand/10 text-brand",
  success: "border-success/20 bg-success/10 text-success",
  warning: "border-warning/20 bg-warning/10 text-warning",
  danger: "border-danger/20 bg-danger/10 text-danger",
  info: "border-info/20 bg-info/10 text-info",
};

interface StatusDotProps {
  tone: Tone;
  live?: boolean;
  /** Required when the dot is shown without a visible label. */
  label?: string;
  className?: string;
}

export function StatusDot({ tone, live = false, label, className }: StatusDotProps) {
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
      className={cn(dotVariants({ tone, live }), className)}
    />
  );
}

interface ToneBadgeProps {
  tone: Tone;
  live?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function ToneBadge({ tone, live = false, children, className }: ToneBadgeProps) {
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-normal", badgeTone[tone], className)}>
      <StatusDot tone={tone} live={live} />
      {children}
    </Badge>
  );
}

interface StatusBadgeProps {
  status: string;
  kind?: "job" | "stage";
  className?: string;
}

export function StatusBadge({ status, kind = "job", className }: StatusBadgeProps) {
  const { label, tone, live } =
    kind === "job" ? describeJobStatus(status) : describeStageStatus(status);
  return (
    <ToneBadge tone={tone} live={live} className={className}>
      {label}
    </ToneBadge>
  );
}

export function ReleaseBadge({ status, className }: { status: string; className?: string }) {
  const { label, tone, description } = describeRelease(status);
  return (
    <ToneBadge tone={tone} className={className}>
      <span title={description}>{label}</span>
    </ToneBadge>
  );
}
