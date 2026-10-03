"use client";

import { useChat } from "@ai-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import { DefaultChatTransport } from "ai";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import type { ForgeMessage } from "@/lib/contract";
import { queryKeys, submitFeedback } from "@/lib/studio/api";
import { dataParts, jobPartOf, latestAssistant, latestJobId } from "@/lib/studio/messages";
import { ChatPanel, type ComposerState } from "./chat-panel";
import { NewProject, type NewProjectRequest } from "./new-project";
import { StudioHeader } from "./studio-header";
import { WorkspacePanel, type WorkspaceTab } from "./workspace-panel";

const LIVE = new Set(["pending", "running", "evaluating", "retrying"]);

/**
 * Stateless: per-request values travel in the `body` passed to sendMessage and
 * resumeStream. A resume without a body (automatic, on page load) uses the
 * chat id, which on /studio/[jobId] is the job id.
 */
const transport = new DefaultChatTransport<ForgeMessage>({
  api: "/api/chat",
  prepareSendMessagesRequest: ({ messages, body }) => ({
    body: { ...body, messages: messages.slice(-1) },
  }),
  prepareReconnectToStreamRequest: ({ id, body }) => ({
    api: `/api/chat/${encodeURIComponent(typeof body?.jobId === "string" ? body.jobId : id)}/stream`,
  }),
});

interface StudioProps {
  /** Fixed for the life of the page; useChat recreates the chat if it changes. */
  chatId?: string;
  initialMessages?: ForgeMessage[];
  resume?: boolean;
  initialProjectName?: string;
}

export function Studio({ chatId, initialMessages = [], resume = false, initialProjectName }: StudioProps) {
  const queryClient = useQueryClient();
  const [fallbackChatId] = useState(() => crypto.randomUUID());
  const [tab, setTab] = useState<WorkspaceTab>("preview");
  const [openRequest, setOpenRequest] = useState<{ path: string; id: number }>();
  // Written only in event handlers: the body of the last send, for retries.
  const lastBody = useRef<Record<string, unknown>>({});

  const chat = useChat<ForgeMessage>({
    id: chatId ?? fallbackChatId,
    messages: initialMessages,
    resume,
    transport,
  });

  const jobId = latestJobId(chat.messages);
  const latest = latestAssistant(chat.messages);
  const job = jobPartOf(latest);
  const streaming = chat.status === "submitted" || chat.status === "streaming";
  const live = job ? LIVE.has(job.status) : false;
  const reviewing = job?.status === "awaiting_human_feedback";

  useEffect(() => {
    if (jobId && window.location.pathname !== `/studio/${jobId}`) {
      // Keep the URL shareable without remounting the chat.
      window.history.replaceState(null, "", `/studio/${jobId}`);
    }
  }, [jobId]);

  useEffect(() => {
    if (job && !LIVE.has(job.status)) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
    }
  }, [job, queryClient]);

  // A job can rewrite its files under the same id (e.g. changes requested at
  // the release gate), so cached files and preview state follow its status.
  const jobStatus = job?.status;
  useEffect(() => {
    if (!jobId || !jobStatus) return;
    for (const key of [["files", jobId], ["file", jobId], ["preview", jobId]]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  }, [jobId, jobStatus, queryClient]);

  function send(text: string, body: Record<string, unknown>) {
    lastBody.current = body;
    void chat.sendMessage({ text }, { body });
  }

  function retry() {
    const last = chat.messages.at(-1);
    if (last?.role !== "user") return;
    const text = last.parts.map((part) => (part.type === "text" ? part.text : "")).join("");
    chat.clearError();
    chat.setMessages((messages) => messages.slice(0, -1));
    send(text, lastBody.current);
  }

  function start({ prompt, projectName, capabilityId }: NewProjectRequest) {
    send(prompt, { projectName: projectName || undefined, capabilityId: capabilityId || undefined });
  }

  async function respond(targetJobId: string, decision: "approve" | "request_changes", note: string) {
    try {
      await submitFeedback(targetJobId, decision, note || undefined);
    } catch (error) {
      toast.error("Your response was not sent", { description: (error as Error).message });
      throw error;
    }
    await chat.resumeStream({ body: { jobId: targetJobId } });
  }

  function openFile(path: string) {
    setOpenRequest((current) => ({ path, id: (current?.id ?? 0) + 1 }));
    setTab("code");
  }

  if (chat.messages.length === 0) {
    return <NewProject sending={streaming} error={chat.error} onStart={start} />;
  }

  const composerState: ComposerState = !job
    ? streaming
      ? "sending"
      : "ready"
    : reviewing
      ? "reviewing"
      : live || streaming
        ? "building"
        : "ready";

  return (
    <div className="flex h-dvh flex-col">
      <StudioHeader
        projectName={latest?.metadata?.projectId ?? initialProjectName ?? "New project"}
        jobId={jobId}
        job={job}
      />
      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="36%" minSize="26%" maxSize="55%">
          <ChatPanel
            messages={chat.messages}
            composerState={composerState}
            error={chat.error}
            errorAction={live ? "reconnect" : chat.messages.at(-1)?.role === "user" ? "retry" : "none"}
            onRetry={retry}
            disconnected={live && !streaming && !chat.error}
            onSend={(text) => {
              send(text, { basedOnJobId: jobId });
            }}
            onReconnect={() => {
              chat.clearError();
              void chat.resumeStream({ body: { jobId } });
            }}
            onDismissError={chat.clearError}
            onApprove={(target, note) => respond(target, "approve", note)}
            onRequestChanges={(target, note) => respond(target, "request_changes", note)}
            onOpenFile={openFile}
          />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel minSize="35%">
          <WorkspacePanel
            key={jobId}
            jobId={jobId}
            job={job}
            streamFiles={latest ? dataParts(latest, "file").map((file) => file.path) : []}
            stages={latest ? dataParts(latest, "stage") : []}
            validation={latest ? dataParts(latest, "validation") : []}
            tab={tab}
            onTabChange={setTab}
            openRequest={openRequest}
          />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
