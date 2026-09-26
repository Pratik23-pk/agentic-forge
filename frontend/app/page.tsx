import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@/components/forge/brand-mark";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-6">
      <div className="flex max-w-md animate-fade flex-col items-start gap-6">
        <BrandMark className="size-8" />
        <div className="flex flex-col gap-2">
          <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.02em]">Agentic Forge</h1>
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            The studio is being rebuilt on a new design system. The working studio stays on the main
            branch until the new workspace lands.
          </p>
        </div>
        <div className="flex gap-2">
          <Button asChild>
            <Link href="/dev/states">
              View the design system
              <ArrowRightIcon data-icon="inline-end" />
            </Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
