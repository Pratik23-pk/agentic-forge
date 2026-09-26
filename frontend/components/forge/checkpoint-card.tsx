"use client";

import { CheckIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";

import { CodeBlock } from "@/components/ai-elements/code-block";
import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRejected,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { CheckpointPart } from "@/lib/contract";

const GATE_LABEL: Record<string, string> = {
  product_contract: "Product contract",
  privileged_action: "Scoped permission",
  release: "Release approval",
  worker_review: "Worker review",
};

export function gateLabel(gate: string): string {
  return GATE_LABEL[gate] ?? "Review";
}

interface CheckpointCardProps {
  checkpoint: CheckpointPart;
  /** May return a promise; the card shows progress and resolves only if it succeeds. */
  onApprove?: (note: string) => void | Promise<void>;
  onRequestChanges?: (note: string) => void | Promise<void>;
}

function CheckpointVisual({ visual }: { visual: string }) {
  const isJson = visual.trimStart().startsWith("{") || visual.trimStart().startsWith("[");
  if (!isJson) {
    return (
      <pre className="overflow-x-auto rounded-md border bg-background px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
        {visual}
      </pre>
    );
  }
  return (
    <Collapsible>
      <CollapsibleTrigger className="group flex items-center gap-1 rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRightIcon
          aria-hidden="true"
          className="size-3.5 transition-transform duration-150 ease-out group-data-[state=open]:rotate-90"
        />
        Show full contract
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2">
        <CodeBlock code={visual} language="json" className="max-h-72 overflow-auto bg-background" />
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * A human approval gate, rendered with the AI SDK confirmation primitive.
 * Once decided it resolves and its actions disappear, so a decision cannot
 * be sent twice.
 */
export function CheckpointCard({ checkpoint, onApprove, onRequestChanges }: CheckpointCardProps) {
  const [note, setNote] = useState("");
  const [askingForChanges, setAskingForChanges] = useState(false);
  const [decision, setDecision] = useState<boolean | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function decide(approved: boolean) {
    const trimmed = note.trim();
    setSubmitting(true);
    try {
      await (approved ? onApprove?.(trimmed) : onRequestChanges?.(trimmed));
      setDecision(approved);
    } catch {
      // The caller reports the error; the card stays actionable so the user can retry.
    } finally {
      setSubmitting(false);
    }
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
        <span className="text-xs text-warning">{gateLabel(checkpoint.gate)}</span>
        <ConfirmationTitle className="text-[13px] font-medium text-foreground">
          {checkpoint.title}
        </ConfirmationTitle>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          {checkpoint.prompt || checkpoint.summary}
        </p>
      </div>
      {checkpoint.visual ? <CheckpointVisual visual={checkpoint.visual} /> : null}
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
        {submitting ? <Spinner className="text-muted-foreground" /> : null}
        {askingForChanges ? (
          <>
            <ConfirmationAction variant="ghost" disabled={submitting} onClick={() => setAskingForChanges(false)}>
              Cancel
            </ConfirmationAction>
            <ConfirmationAction
              variant="secondary"
              disabled={!note.trim() || submitting}
              onClick={() => decide(false)}
            >
              Send changes
            </ConfirmationAction>
          </>
        ) : (
          <>
            <ConfirmationAction variant="ghost" disabled={submitting} onClick={() => setAskingForChanges(true)}>
              Request changes
            </ConfirmationAction>
            <ConfirmationAction disabled={submitting} onClick={() => decide(true)}>
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
