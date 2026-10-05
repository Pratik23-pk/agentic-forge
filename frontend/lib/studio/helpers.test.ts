import { describe, expect, it } from "vitest";

import type { ForgeMessage } from "@/lib/contract";
import { formatBytes, formatRelativeTime } from "./format";
import { editorLanguage, isEditableFile } from "./language";
import { dataParts, jobPartOf, latestJobId, orderedStages } from "./messages";
import { sha256Hex } from "./sha256";

const assistant = (jobId: string, parts: ForgeMessage["parts"]): ForgeMessage => ({
  id: `job-${jobId}`,
  role: "assistant",
  metadata: { jobId, projectId: "P" },
  parts,
});

describe("latestJobId", () => {
  it("returns the job of the last assistant message", () => {
    const messages: ForgeMessage[] = [
      assistant("a", []),
      { id: "u", role: "user", parts: [{ type: "text", text: "change" }] },
      assistant("b", []),
    ];
    expect(latestJobId(messages)).toBe("b");
  });

  it("is undefined before any build", () => {
    expect(latestJobId([{ id: "u", role: "user", parts: [{ type: "text", text: "hi" }] }])).toBeUndefined();
  });
});

describe("parts", () => {
  const message = assistant("a", [
    { type: "data-stage", id: "stage-release", data: { stage: "release", status: "queued" } },
    { type: "data-stage", id: "stage-frontend", data: { stage: "frontend", status: "running" } },
    { type: "data-stage", id: "stage-plan", data: { stage: "plan", status: "done" } },
    {
      type: "data-job",
      id: "job",
      data: { status: "running", releaseStatus: "pending", costUsd: 0, budgetUsd: 1, usedFallback: false, artifactsReady: false },
    },
  ]);

  it("filters data parts by kind", () => {
    expect(dataParts(message, "stage")).toHaveLength(3);
  });

  it("orders stages by pipeline position regardless of arrival order", () => {
    expect(orderedStages(message).map((stage) => stage.stage)).toEqual(["plan", "frontend", "release"]);
  });

  it("finds the job part", () => {
    expect(jobPartOf(message)?.status).toBe("running");
    expect(jobPartOf(assistant("b", []))).toBeUndefined();
  });
});

describe("editorLanguage", () => {
  it("detects languages by extension", () => {
    expect(editorLanguage("src/App.tsx")).toBe("tsx");
    expect(editorLanguage("api/main.py")).toBe("python");
    expect(editorLanguage("README.md")).toBe("markdown");
    expect(editorLanguage("migrations/001.sql")).toBe("sql");
    expect(editorLanguage("Dockerfile")).toBe("text");
  });

  it("treats common text files as editable and binaries as not", () => {
    expect(isEditableFile("Dockerfile")).toBe(true);
    expect(isEditableFile("requirements.txt")).toBe(true);
    expect(isEditableFile(".gitignore")).toBe(true);
    expect(isEditableFile("public/logo.png")).toBe(false);
    expect(isEditableFile("fonts/inter.woff2")).toBe(false);
  });
});

describe("format", () => {
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5 MB");
  });

  it("formats relative time", () => {
    const now = new Date("2026-09-26T12:00:00Z").getTime();
    expect(formatRelativeTime("2026-09-26T11:59:30Z", now)).toBe("just now");
    expect(formatRelativeTime("2026-09-26T11:55:00Z", now)).toBe("5 minutes ago");
    expect(formatRelativeTime("2026-09-25T12:00:00Z", now)).toBe("yesterday");
  });
});

describe("sha256Hex", () => {
  it("matches the backend's hex digest", async () => {
    expect(await sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });
});
