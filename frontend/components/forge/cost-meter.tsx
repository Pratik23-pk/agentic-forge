import { cn } from "@/lib/utils";

interface CostMeterProps {
  spentUsd: number;
  budgetUsd: number;
  promptTokens?: number;
  completionTokens?: number;
  className?: string;
}

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** Spend against the per-run budget, as reported by the backend cost ledger. */
export function CostMeter({
  spentUsd,
  budgetUsd,
  promptTokens,
  completionTokens,
  className,
}: CostMeterProps) {
  const ratio = budgetUsd > 0 ? Math.min(spentUsd / budgetUsd, 1) : 0;
  const tone = ratio >= 0.9 ? "bg-danger" : ratio >= 0.7 ? "bg-warning" : "bg-foreground/70";

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-baseline justify-between gap-4 text-xs">
        <span className="text-muted-foreground">Run cost</span>
        <span className="tabular">
          <span className="text-foreground">{usd.format(spentUsd)}</span>
          <span className="text-subtle-foreground"> of {usd.format(budgetUsd)}</span>
        </span>
      </div>
      <div
        role="meter"
        aria-label="Run cost against budget"
        aria-valuemin={0}
        aria-valuemax={budgetUsd}
        aria-valuenow={spentUsd}
        className="h-1 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn("h-full origin-left rounded-full transition-transform duration-300 ease-out", tone)}
          style={{ transform: `scaleX(${ratio})` }}
        />
      </div>
      {promptTokens !== undefined && completionTokens !== undefined ? (
        <p className="tabular text-xs text-subtle-foreground">
          {compact.format(promptTokens)} in · {compact.format(completionTokens)} out
        </p>
      ) : null}
    </div>
  );
}
