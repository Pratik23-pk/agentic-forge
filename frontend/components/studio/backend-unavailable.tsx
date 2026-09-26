import Link from "next/link";

import { Wordmark } from "@/components/forge/brand-mark";
import { Button } from "@/components/ui/button";

export function BackendUnavailable({ message }: { message: string }) {
  return (
    <main className="flex min-h-dvh flex-col">
      <header className="flex h-12 items-center border-b px-4">
        <Link href="/studio" className="rounded-md" aria-label="Studio home">
          <Wordmark />
        </Link>
      </header>
      <div className="flex flex-1 items-center justify-center px-6">
        <div className="flex max-w-sm flex-col items-start gap-3">
          <p className="font-mono text-xs text-subtle-foreground">Backend unavailable</p>
          <h1 className="text-xl font-medium tracking-tight">This project could not be loaded</h1>
          <p className="text-[13px] text-muted-foreground">{message}</p>
          <p className="text-[13px] text-muted-foreground">
            Start it with <code className="text-foreground">./scripts/run_backend.sh</code>, then reload.
          </p>
          <Button asChild variant="secondary" size="sm">
            <Link href="/studio">Back to projects</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
