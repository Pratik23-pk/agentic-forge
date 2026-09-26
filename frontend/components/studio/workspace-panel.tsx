"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { JobPart, StagePart, ValidationPart } from "@/lib/contract";
import { ActivityTab } from "./activity-tab";
import { CodeTab } from "./code-tab";
import { PreviewTab } from "./preview-tab";

export type WorkspaceTab = "preview" | "code" | "activity";

interface WorkspacePanelProps {
  jobId: string | undefined;
  job: JobPart | undefined;
  streamFiles: string[];
  stages: StagePart[];
  validation: ValidationPart[];
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  openPath: string | undefined;
  onOpenPath: (path: string) => void;
}

export function WorkspacePanel({
  jobId,
  job,
  streamFiles,
  stages,
  validation,
  tab,
  onTabChange,
  openPath,
  onOpenPath,
}: WorkspacePanelProps) {
  return (
    <Tabs
      value={tab}
      onValueChange={(value) => onTabChange(value as WorkspaceTab)}
      className="flex h-full min-h-0 flex-col gap-0"
    >
      <div className="flex h-10 shrink-0 items-center border-b px-2">
        <TabsList variant="line">
          <TabsTrigger value="preview">Preview</TabsTrigger>
          <TabsTrigger value="code">Code</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>
      </div>
      {/* Tabs stay mounted so a running preview and unsaved edits survive switching. */}
      <TabsContent value="preview" forceMount className="min-h-0 flex-1 data-[state=inactive]:hidden">
        <PreviewTab jobId={jobId} job={job} />
      </TabsContent>
      <TabsContent value="code" forceMount className="min-h-0 flex-1 data-[state=inactive]:hidden">
        <CodeTab jobId={jobId} job={job} streamFiles={streamFiles} openPath={openPath} onOpenPath={onOpenPath} />
      </TabsContent>
      <TabsContent value="activity" forceMount className="min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
        <ActivityTab job={job} stages={stages} validation={validation} />
      </TabsContent>
    </Tabs>
  );
}
