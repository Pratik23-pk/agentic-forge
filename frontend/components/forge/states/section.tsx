import { cn } from "@/lib/utils";

interface SectionProps {
  id: string;
  title: string;
  description: string;
  children: React.ReactNode;
}

export function Section({ id, title, description, children }: SectionProps) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-20 border-t py-14 first:border-t-0 first:pt-0">
      <header className="mb-8 max-w-xl">
        <h2 id={`${id}-title`} className="text-base font-medium">
          {title}
        </h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{description}</p>
      </header>
      <div className="flex flex-col gap-10">{children}</div>
    </section>
  );
}

export function Specimen({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <h3 className="text-xs font-normal text-subtle-foreground">{label}</h3>
      <div className={cn("rounded-xl border bg-card p-5", className)}>{children}</div>
    </div>
  );
}
