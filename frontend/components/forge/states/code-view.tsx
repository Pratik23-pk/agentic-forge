"use client";

import { useState } from "react";

import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockCopyButton,
  CodeBlockHeader,
} from "@/components/ai-elements/code-block";
import { ProjectFiles } from "@/components/forge/project-files";
import { ToneBadge } from "@/components/forge/status";
import { CODE_SAMPLE, FILES } from "@/lib/fixtures";
import { Section } from "./section";

const bytes = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

function formatBytes(size: number) {
  return size < 1024 ? `${size} B` : `${bytes.format(size / 1024)} KB`;
}

export function CodeView() {
  const [selected, setSelected] = useState(FILES[5].path);
  const file = FILES.find((item) => item.path === selected) ?? FILES[0];

  return (
    <Section
      id="code"
      title="Code"
      description="Files arrive as the workers write them. Long paths truncate from the middle of the layout, never the frame, and the full path is always one hover away."
    >
      <div className="grid overflow-hidden rounded-xl border bg-card md:grid-cols-[300px_1fr]">
        <div className="border-b p-2 md:border-r md:border-b-0">
          <ProjectFiles
            paths={FILES.map((item) => item.path)}
            selectedPath={selected}
            onSelect={setSelected}
            className="border-0 bg-transparent"
          />
        </div>
        <div className="min-w-0 p-3">
          <CodeBlock code={CODE_SAMPLE} language="tsx" showLineNumbers className="bg-background">
            <CodeBlockHeader>
              <span className="min-w-0 truncate font-mono" title={file.path}>
                {file.path}
              </span>
              <CodeBlockActions>
                {file.op === "patch" ? <ToneBadge tone="info">Patched</ToneBadge> : null}
                <span className="tabular hidden text-subtle-foreground sm:inline">{formatBytes(file.bytes)}</span>
                <CodeBlockCopyButton />
              </CodeBlockActions>
            </CodeBlockHeader>
          </CodeBlock>
        </div>
      </div>
    </Section>
  );
}
