import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-6">
      <div className="flex max-w-sm flex-col items-start gap-4">
        <p className="font-mono text-xs text-subtle-foreground">404</p>
        <h1 className="text-xl font-medium tracking-tight">This page does not exist</h1>
        <p className="text-[13px] text-muted-foreground">The link may be out of date, or the project was removed.</p>
        <Button asChild variant="secondary" size="sm">
          <Link href="/">Back to Agentic Forge</Link>
        </Button>
      </div>
    </main>
  );
}
