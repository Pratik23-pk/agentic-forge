import { describe, expect, it } from "vitest";

import { describeBackendError } from "@/lib/backend/client";
import { buildFollowUpPrompt, lastUserText } from "./prompt";

describe("buildFollowUpPrompt", () => {
  it("combines the original request with every change, without nesting", () => {
    const prompt = buildFollowUpPrompt("Build a habit tracker.", ["  Add streaks.  ", "Dark mode"]);
    expect(prompt).toContain("Original request:\nBuild a habit tracker.");
    expect(prompt).toContain("1. Add streaks.\n2. Dark mode");
    expect(prompt.match(/Build a new version/g)).toHaveLength(1);
  });
});

describe("lastUserText", () => {
  it("returns the text of the latest user message", () => {
    expect(
      lastUserText([
        { id: "1", role: "user", parts: [{ type: "text", text: "first" }] },
        { id: "2", role: "assistant", parts: [{ type: "text", text: "reply" }] },
        { id: "3", role: "user", parts: [{ type: "text", text: " second " }] },
      ]),
    ).toBe("second");
  });

  it("returns an empty string without a user message", () => {
    expect(lastUserText([])).toBe("");
  });
});

describe("describeBackendError", () => {
  it("reads string, policy and validation details", () => {
    expect(describeBackendError(404, { detail: "Job not found." })).toBe("Job not found.");
    expect(
      describeBackendError(422, { detail: { code: "prohibited_request", message: "Request rejected." } }),
    ).toBe("Request rejected.");
    expect(describeBackendError(422, { detail: [{ msg: "Field required" }] })).toBe("Field required");
  });

  it("explains an unavailable backend", () => {
    expect(describeBackendError(503, null)).toMatch(/unavailable/);
    expect(describeBackendError(500, null)).toMatch(/500/);
  });
});
