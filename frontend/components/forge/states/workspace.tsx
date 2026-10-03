"use client";

import { DownloadIcon, GitBranchIcon } from "lucide-react";
import { toast } from "sonner";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { CostMeter } from "@/components/forge/cost-meter";
import { ProjectFiles } from "@/components/forge/project-files";
import { StageList } from "@/components/forge/stage-list";
import { StatusBadge } from "@/components/forge/status";
import { Wordmark } from "@/components/forge/brand-mark";
import { ValidationResults } from "@/components/forge/validation-results";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ASSISTANT_SUMMARY,
  COST,
  FILES,
  LONG_PROJECT_NAME,
  PROMPT,
  STAGES_BUILDING,
  VALIDATION_PASSING,
} from "@/lib/fixtures";
import { PreviewFrame } from "./preview-states";
import { Section } from "./section";

export function Workspace() {
  return (
    <Section
      id="workspace"
      title="Workspace"
      description="The studio composed from the pieces above: conversation on the left, the running app on the right. The project name is deliberately long to prove the top bar holds."
    >
      <div className="flex h-[720px] flex-col overflow-hidden rounded-xl border bg-background">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b px-3">
          <Wordmark />
          <span className="text-border-strong" aria-hidden="true">
            /
          </span>
          <span className="min-w-0 flex-1 truncate text-[13px]" title={LONG_PROJECT_NAME}>
            {LONG_PROJECT_NAME}
          </span>
          <StatusBadge status="running" />
          <Button variant="ghost" size="sm">
            <DownloadIcon data-icon="inline-start" />
            ZIP
          </Button>
          <Button size="sm">
            <GitBranchIcon data-icon="inline-start" />
            Publish
          </Button>
        </header>

        <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
          <ResizablePanel defaultSize="36%" minSize="26%" maxSize="50%">
            <div className="flex h-full flex-col">
              <Conversation className="min-h-0">
                <ConversationContent className="gap-6 p-4">
                  <Message from="user">
                    <MessageContent>{PROMPT}</MessageContent>
                  </Message>
                  <Message from="assistant">
                    <MessageContent>
                      <MessageResponse>{ASSISTANT_SUMMARY}</MessageResponse>
                    </MessageContent>
                  </Message>
                  <div className="rounded-lg border bg-card p-3">
                    <StageList stages={STAGES_BUILDING} />
                  </div>
                </ConversationContent>
                <ConversationScrollButton />
              </Conversation>
              <div className="border-t p-3">
                <PromptInput
                  onSubmit={(message) => {
                    toast("Change requested", { description: message.text || "Empty message" });
                  }}
                >
                  <PromptInputBody>
                    <PromptInputTextarea placeholder="Ask for a change" />
                  </PromptInputBody>
                  <PromptInputFooter>
                    <PromptInputTools>
                      <span className="px-2 text-xs text-subtle-foreground">React + FastAPI</span>
                    </PromptInputTools>
                    <PromptInputSubmit />
                  </PromptInputFooter>
                </PromptInput>
              </div>
            </div>
          </ResizablePanel>

          <ResizableHandle />

          <ResizablePanel minSize="40%">
            <Tabs defaultValue="preview" className="flex h-full flex-col gap-0">
              <div className="flex h-10 shrink-0 items-center border-b px-2">
                <TabsList variant="line">
                  <TabsTrigger value="preview">Preview</TabsTrigger>
                  <TabsTrigger value="code">Code</TabsTrigger>
                  <TabsTrigger value="activity">Activity</TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="preview" className="min-h-0 flex-1 p-2">
                <PreviewFrame className="h-full" />
              </TabsContent>
              <TabsContent value="code" className="min-h-0 flex-1 overflow-auto p-2">
                <ProjectFiles paths={FILES.map((file) => file.path)} className="border-0 bg-transparent" />
              </TabsContent>
              <TabsContent value="activity" className="min-h-0 flex-1 overflow-auto p-4">
                <div className="mx-auto flex max-w-xl flex-col gap-6">
                  <CostMeter
                    spentUsd={COST.spentUsd}
                    budgetUsd={COST.budgetUsd}
                    promptTokens={COST.promptTokens}
                    completionTokens={COST.completionTokens}
                  />
                  <ValidationResults results={VALIDATION_PASSING} />
                </div>
              </TabsContent>
            </Tabs>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </Section>
  );
}
