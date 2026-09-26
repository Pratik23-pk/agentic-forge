import { cn } from "@/lib/utils";

/**
 * Three stacked ingots on an ember tile: layers of work, forged in order.
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
        <rect x="6" y="6.5" width="12" height="2.5" rx="1.25" />
        <rect x="7.5" y="10.75" width="9" height="2.5" rx="1.25" />
        <rect x="9" y="15" width="6" height="2.5" rx="1.25" />
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
