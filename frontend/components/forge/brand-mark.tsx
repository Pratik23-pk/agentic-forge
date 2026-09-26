import { cn } from "@/lib/utils";

/**
 * Three ingots stacked on an ember tile: work built up in layers.
 * Decorative; pair it with the wordmark or an accessible label.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={cn("size-5 shrink-0 text-brand", className)}
    >
      <rect width="24" height="24" rx="6" fill="currentColor" />
      <g fill="var(--brand-foreground)">
        <rect x="9.5" y="6" width="5" height="3" rx="0.75" />
        <rect x="7.5" y="10.5" width="9" height="3" rx="0.75" />
        <rect x="5.5" y="15" width="13" height="3" rx="0.75" />
      </g>
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <BrandMark />
      <span className="text-[13px] font-medium tracking-tight">Agentic Forge</span>
    </span>
  );
}
