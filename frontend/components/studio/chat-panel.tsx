"use client";

import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ForgeMessage } from "@/lib/contract";
import { AssistantMessage } from "./assistant-message";

export type ComposerState = "ready" | "building" | "reviewing" | "sending";

const PLACEHOLDER: Record<ComposerState, string> = {
  ready: "Describe a change for the next version",
  building: "The build is running. You can ask for changes when it finishes.",
  reviewing: "Approve or request changes above to continue.",
  sending: "Starting the build",
};

interface ChatPanelProps {
  messages: ForgeMessage[];
  composerState: ComposerState;
  error: Error | undefined;
  /** True when a build is live but this page is not receiving its stream. */
  disconnected: boolean;
  onSend: (text: string) => void;
  onReconnect: () => void;
  onDismissError: () => void;
  onApprove: (jobId: string, note: string) => Promise<void>;
  onRequestChanges: (jobId: string, note: string) => Promise<void>;
  onOpenFile: (path: string) => void;
}

function userText(message: ForgeMessage): string {
  return message.parts.map((part) => (part.type === "text" ? part.text : "")).join("");
}

export function ChatPanel({
  messages,
  composerState,
  error,
  disconnected,
  onSend,
  onReconnect,
  onDismissError,
  onApprove,
  onRequestChanges,
  onOpenFile,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const lastAssistantIndex = messages.findLastIndex((message) => message.role === "assistant");
  const canSend = composerState === "ready" && draft.trim().length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Conversation className="min-h-0">
        <ConversationContent className="gap-6 p-4">
          {messages.map((message, index) =>
            message.role === "user" ? (
              <Message key={message.id} from="user">
                <MessageContent className="whitespace-pre-wrap">{userText(message)}</MessageContent>
              </Message>
            ) : (
              <AssistantMessage
                key={message.id}
                message={message}
                isLatest={index === lastAssistantIndex}
                onApprove={onApprove}
                onRequestChanges={onRequestChanges}
                onOpenFile={onOpenFile}
              />
            ),
          )}

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Something went wrong</AlertTitle>
              <AlertDescription>
                <p className="break-words">{error.message}</p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="secondary" onClick={onReconnect}>
                    Reconnect
                  </Button>
                  <Button size="sm" variant="ghost" onClick={onDismissError}>
                    Dismiss
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : disconnected ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-xs text-muted-foreground">
              The build is still running on the server.
              <Button size="sm" variant="ghost" onClick={onReconnect}>
                <RefreshCwIcon data-icon="inline-start" />
                Follow progress
              </Button>
            </div>
          ) : null}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="border-t p-3">
        <PromptInput
          onSubmit={() => {
            if (!canSend) return;
            onSend(draft.trim());
            setDraft("");
          }}
        >
          <PromptInputBody>
            <PromptInputTextarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={PLACEHOLDER[composerState]}
              disabled={composerState !== "ready"}
              className="min-h-14 text-[13px]"
            />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              <span className="px-2 text-xs text-subtle-foreground">
                Each change builds a new version from scratch.
              </span>
            </PromptInputTools>
            <PromptInputSubmit
              disabled={!canSend}
              status={composerState === "sending" ? "submitted" : "ready"}
              aria-label="Build new version"
            />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </div>
  );
}
