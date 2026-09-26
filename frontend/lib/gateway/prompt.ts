import type { UIMessage } from "ai";

/**
 * The backend has no incremental edit endpoint, so a follow-up request builds
 * a new version from the original request plus the change.
 */
export function buildFollowUpPrompt(originalPrompt: string, change: string): string {
  return [
    "Build a new version of an existing project.",
    "",
    "Original request:",
    originalPrompt.trim(),
    "",
    "Changes for this version:",
    change.trim(),
    "",
    "Keep everything from the original request unless the changes say otherwise.",
  ].join("\n");
}

export function lastUserText(messages: readonly UIMessage[]): string {
  const last = [...messages].reverse().find((message) => message.role === "user");
  if (!last) return "";
  return last.parts
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
    .trim();
}
