import { describe, expect, it } from "vitest";

import { summarizeError } from "./errors";

describe("summarizeError", () => {
  it("names a failed npm install instead of dumping npm output", () => {
    const raw = "Preview dependency preparation failed: @2.3.2 from lock file\nnpm error Missing: expect-type@1.4.0 from lock file\nnpm error Clean install a project";
    expect(summarizeError(raw)).toEqual({
      summary: "Installing the app's dependencies failed: the lockfile does not match package.json.",
      details: raw,
    });
  });

  it("keeps short single-line errors as they are", () => {
    expect(summarizeError("Preview not found.")).toEqual({ summary: "Preview not found.", details: undefined });
  });

  it("explains a stopped Docker daemon", () => {
    expect(summarizeError("Docker is unavailable.").summary).toMatch(/start docker desktop/i);
  });

  it("uses the first line of long errors and keeps the rest as details", () => {
    const raw = `Backend exited during startup\n${"Traceback line\n".repeat(20)}`;
    const result = summarizeError(raw);
    expect(result.summary).toBe("Backend exited during startup");
    expect(result.details).toBe(raw.trim());
  });

  it("truncates a very long first line", () => {
    const result = summarizeError("x".repeat(400));
    expect(result.summary.length).toBeLessThanOrEqual(161);
    expect(result.details).toHaveLength(400);
  });
});
