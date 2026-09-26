"use client";

import { CheckIcon } from "lucide-react";
import { useState } from "react";

import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRejected,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { Textarea } from "@/components/ui/textarea";
import type { CheckpointPart } from "@/lib/contract";

const GATE_LABEL: Record<CheckpointPart["gate"], string> = {
  product_contract: "Product contract",
  privileged_action: "Scoped permission",
  release: "Release approval",
  worker_review: "Worker review",
};

interface CheckpointCardProps {
  checkpoint: CheckpointPart;
  onApprove?: (note: string) => void;
  onRequestChanges?: (note: string) => void;
}

/**
 * A human approval gate. Rendered with the AI SDK confirmation primitive so
 * Phase 2 can map backend checkpoints onto tool approval requests directly.
 */
export function CheckpointCard({ checkpoint, onApprove, onRequestChanges }: CheckpointCardProps) {
  const [note, setNote] = useState("");
  const [askingForChanges, setAskingForChanges] = useState(false);
  // Once decided, the card resolves and its actions disappear, so a decision
  // cannot be sent twice.
  const [decision, setDecision] = useState<boolean | null>(null);

  function decide(approved: boolean) {
    setDecision(approved);
    const trimmed = note.trim();
    if (approved) onApprove?.(trimmed);
    else onRequestChanges?.(trimmed);
  }

  return (
    <Confirmation
      approval={
        decision === null
          ? { id: checkpoint.checkpointId }
          : { id: checkpoint.checkpointId, approved: decision, reason: note.trim() || undefined }
      }
      state={decision === null ? "approval-requested" : "approval-responded"}
      className="gap-3 border-warning/20"
    >
      <div className="flex flex-col gap-1">
        <span className="text-xs text-warning">{GATE_LABEL[checkpoint.gate]}</span>
        <ConfirmationTitle className="text-[13px] font-medium text-foreground">
          {checkpoint.title}
        </ConfirmationTitle>
        <p className="text-[13px] leading-relaxed text-muted-foreground">{checkpoint.summary}</p>
      </div>
      {checkpoint.visual ? (
        <pre className="overflow-x-auto rounded-md border bg-background px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
          {checkpoint.visual}
        </pre>
      ) : null}
      <ConfirmationRequest>
        {askingForChanges ? (
          <Textarea
            aria-label="Describe the change you want"
            autoFocus
            placeholder="Describe what should change"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="min-h-16 text-[13px]"
          />
        ) : null}
      </ConfirmationRequest>
      <ConfirmationActions>
        {askingForChanges ? (
          <>
            <ConfirmationAction variant="ghost" onClick={() => setAskingForChanges(false)}>
              Cancel
            </ConfirmationAction>
            <ConfirmationAction
              variant="secondary"
              disabled={!note.trim()}
              onClick={() => decide(false)}
            >
              Send changes
            </ConfirmationAction>
          </>
        ) : (
          <>
            <ConfirmationAction variant="ghost" onClick={() => setAskingForChanges(true)}>
              Request changes
            </ConfirmationAction>
            <ConfirmationAction onClick={() => decide(true)}>
              <CheckIcon data-icon="inline-start" />
              Approve
            </ConfirmationAction>
          </>
        )}
      </ConfirmationActions>
      <ConfirmationAccepted>
        <p className="flex items-center gap-1.5 text-[13px] text-success">
          <CheckIcon className="size-3.5" aria-hidden="true" />
          Approved. The build continues.
        </p>
      </ConfirmationAccepted>
      <ConfirmationRejected>
        <p className="text-[13px] text-muted-foreground">
          Changes requested: <span className="text-foreground">{note.trim()}</span>
        </p>
      </ConfirmationRejected>
    </Confirmation>
  );
}
