import type { Metadata } from "next";
import Link from "next/link";

import { Wordmark } from "@/components/forge/brand-mark";
import { BuildStream } from "@/components/forge/states/build-stream";
import { CodeView } from "@/components/forge/states/code-view";
import { Foundations } from "@/components/forge/states/foundations";
import { PreviewStates } from "@/components/forge/states/preview-states";
import { Primitives } from "@/components/forge/states/primitives";
import { SectionNav } from "@/components/forge/states/section-nav";
import { StatusGallery } from "@/components/forge/states/status-gallery";
import { Workspace } from "@/components/forge/states/workspace";

export const metadata: Metadata = {
  title: "Design system",
  robots: { index: false, follow: false },
};

export default function DesignStatesPage() {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-40 border-b bg-background">
        <div className="mx-auto flex h-12 max-w-7xl items-center gap-3 px-6">
          <Link href="/" className="rounded-md" aria-label="Agentic Forge home">
            <Wordmark />
          </Link>
          <span className="text-border-strong" aria-hidden="true">
            /
          </span>
          <span className="text-[13px] text-muted-foreground">Design system</span>
          <span className="ml-auto font-mono text-xs text-subtle-foreground">Phase 1</span>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-12 px-6 py-12 lg:grid-cols-[180px_1fr]">
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <SectionNav />
          </div>
        </aside>
        <main className="min-w-0">
          <div className="mb-14 max-w-2xl">
            <h1 className="text-[28px] leading-9 font-semibold tracking-[-0.02em]">Design system</h1>
            <p className="mt-3 text-[15px] leading-relaxed text-muted-foreground">
              The reference for every surface in the studio, rendered from fixtures that follow the
              streaming contract. If it ships in the product, it appears here first.
            </p>
          </div>
          <Foundations />
          <Primitives />
          <StatusGallery />
          <BuildStream />
          <CodeView />
          <PreviewStates />
          <Workspace />
        </main>
      </div>
    </div>
  );
}
