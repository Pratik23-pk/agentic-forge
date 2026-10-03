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
            Describe a product and get a planned, built and tested project you can run, edit and
            download.
          </p>
        </div>
        <div className="flex gap-2">
          <Button asChild>
            <Link href="/studio">
              Open the studio
              <ArrowRightIcon data-icon="inline-end" />
            </Link>
          </Button>
          <Button asChild variant="ghost">
            <Link href="/dev/states">Design system</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
