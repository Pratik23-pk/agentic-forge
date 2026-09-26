import type { ForgeDataParts, ForgeMessage, JobPart, StageId, StagePart } from "@/lib/contract";

const STAGE_ORDER: StageId[] = ["plan", "design", "database", "backend", "frontend", "validate", "evaluate", "release"];

export function latestJobId(messages: readonly ForgeMessage[]): string | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant" && message.metadata?.jobId) return message.metadata.jobId;
  }
  return undefined;
}

export function latestAssistant(messages: readonly ForgeMessage[]): ForgeMessage | undefined {
  return [...messages].reverse().find((message) => message.role === "assistant");
}

export function dataParts<K extends keyof ForgeDataParts>(
  message: ForgeMessage,
  kind: K,
): Array<ForgeDataParts[K]> {
  return message.parts
    .filter((part) => part.type === `data-${kind}`)
    .map((part) => (part as unknown as { data: ForgeDataParts[K] }).data);
}

/** Stages in pipeline order; parts arrive in whatever order the build discovers them. */
export function orderedStages(message: ForgeMessage): StagePart[] {
  return dataParts(message, "stage").sort(
    (a, b) => STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage),
  );
}

export function jobPartOf(message: ForgeMessage | undefined): JobPart | undefined {
  return message ? dataParts(message, "job")[0] : undefined;
}

export function summaryOf(message: ForgeMessage): string | undefined {
  return dataParts(message, "summary")[0]?.text;
}
