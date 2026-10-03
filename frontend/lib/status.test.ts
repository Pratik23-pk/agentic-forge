import { describe, expect, it } from "vitest";

import { describeJobStatus, describeRelease, describeStageStatus } from "./status";

describe("describeJobStatus", () => {
  it("marks running work as live brand", () => {
    expect(describeJobStatus("running")).toEqual({ label: "Building", tone: "brand", live: true });
  });

  it("maps awaiting_human_feedback to a review state", () => {
    expect(describeJobStatus("awaiting_human_feedback")).toEqual({
      label: "Needs review",
      tone: "warning",
      live: false,
    });
  });

  it("treats retrying and evaluating as live work", () => {
    expect(describeJobStatus("retrying").live).toBe(true);
    expect(describeJobStatus("evaluating").live).toBe(true);
  });

  it("falls back to a neutral label for unknown statuses", () => {
    expect(describeJobStatus("teleporting")).toEqual({
      label: "Unknown",
      tone: "neutral",
      live: false,
    });
  });
});

describe("describeStageStatus", () => {
  it("maps done to success", () => {
    expect(describeStageStatus("done")).toEqual({ label: "Done", tone: "success", live: false });
  });

  it("maps running to a live brand state", () => {
    expect(describeStageStatus("running").live).toBe(true);
  });

  it("falls back for unknown stage statuses", () => {
    expect(describeStageStatus("").tone).toBe("neutral");
  });
});

describe("describeRelease", () => {
  it("explains quarantined builds", () => {
    const release = describeRelease("quarantined");
    expect(release.tone).toBe("danger");
    expect(release.description).toMatch(/publication is locked/i);
  });

  it("marks verified builds as success", () => {
    expect(describeRelease("verified").tone).toBe("success");
  });

  it("falls back for unknown release statuses", () => {
    expect(describeRelease("shipped?").label).toBe("Unknown");
  });
});
