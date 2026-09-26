"use client";

import { CheckIcon } from "lucide-react";
import { toast } from "sonner";

import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import {
  Plan,
  PlanContent,
  PlanDescription,
  PlanHeader,
  PlanTitle,
  PlanTrigger,
} from "@/components/ai-elements/plan";
import { CheckpointCard } from "@/components/forge/checkpoint-card";
import { CostMeter } from "@/components/forge/cost-meter";
import { FallbackNotice } from "@/components/forge/fallback-notice";
import { StageList } from "@/components/forge/stage-list";
import { StatusBadge } from "@/components/forge/status";
import { ValidationResults } from "@/components/forge/validation-results";
import {
  ASSISTANT_SUMMARY,
  CHECKPOINT,
  COST,
  PLAN_STEPS,
  PROMPT,
  STAGES_BUILDING,
  STAGES_REPAIRING,
  STAGES_VERIFIED,
  VALIDATION_FAILING,
  VALIDATION_PASSING,
} from "@/lib/fixtures";
import { Section, Specimen } from "./section";

export function BuildStream() {
  return (
    <Section
      id="build-stream"
      title="Build stream"
      description="What the gateway streams into the conversation: the plan, stage progress, approval gates, validation evidence and cost. Every part updates in place as the build moves."
    >
      <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
        <Specimen label="Conversation">
          <div className="flex flex-col gap-6">
            <Message from="user">
              <MessageContent>{PROMPT}</MessageContent>
            </Message>
            <Message from="assistant">
              <MessageContent>
                <MessageResponse>{ASSISTANT_SUMMARY}</MessageResponse>
              </MessageContent>
            </Message>
            <Plan defaultOpen>
              <PlanHeader>
                <div className="flex flex-col gap-1">
                  <PlanTitle>Implementation plan</PlanTitle>
                  <PlanDescription>Five steps across three workers</PlanDescription>
                </div>
                <PlanTrigger />
              </PlanHeader>
              <PlanContent>
                <ol className="flex flex-col gap-2">
                  {PLAN_STEPS.map((step, index) => (
                    <li key={step} className="grid grid-cols-[20px_1fr] gap-2 text-[13px]">
                      <span className="tabular text-subtle-foreground">{index + 1}</span>
                      <span className="text-muted-foreground">{step}</span>
                    </li>
                  ))}
                </ol>
              </PlanContent>
            </Plan>
          </div>
        </Specimen>
        <Specimen label="Stages · building">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[13px] font-medium">Roastery Portal</span>
            <StatusBadge status="running" />
          </div>
          <StageList stages={STAGES_BUILDING} />
          <div className="mt-4 border-t pt-4">
            <CostMeter
              spentUsd={COST.spentUsd}
              budgetUsd={COST.budgetUsd}
              promptTokens={COST.promptTokens}
              completionTokens={COST.completionTokens}
            />
          </div>
        </Specimen>
      </div>

      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Approval gate" className="rounded-none border-0 bg-transparent p-0">
          <CheckpointCard
            checkpoint={CHECKPOINT}
            onApprove={() => toast("Contract approved", { icon: <CheckIcon className="size-4" /> })}
            onRequestChanges={(note) => toast("Changes requested", { description: note })}
          />
        </Specimen>
        <div className="flex flex-col gap-10">
          <Specimen label="Stages · repairing">
            <StageList stages={STAGES_REPAIRING} />
          </Specimen>
          <Specimen label="Stages · verified">
            <StageList stages={STAGES_VERIFIED.slice(4)} />
          </Specimen>
        </div>
      </div>

      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Validation · passing" className="rounded-none border-0 bg-transparent p-0">
          <ValidationResults results={VALIDATION_PASSING} />
        </Specimen>
        <Specimen label="Validation · failing" className="rounded-none border-0 bg-transparent p-0">
          <ValidationResults results={VALIDATION_FAILING} />
        </Specimen>
      </div>

      <Specimen label="Template fallback">
        <FallbackNotice />
      </Specimen>
    </Section>
  );
}
