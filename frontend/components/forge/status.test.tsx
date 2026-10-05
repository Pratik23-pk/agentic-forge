import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReleaseBadge, StatusBadge, StatusDot } from "./status";

describe("StatusBadge", () => {
  it("renders a readable label for a job status", () => {
    render(<StatusBadge status="awaiting_human_feedback" />);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });

  it("renders Unknown instead of crashing on an unexpected status", () => {
    render(<StatusBadge status="teleporting" />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("uses stage labels when kind is stage", () => {
    render(<StatusBadge status="done" kind="stage" />);
    expect(screen.getByText("Done")).toBeInTheDocument();
  });
});

describe("ReleaseBadge", () => {
  it("exposes the release description as a tooltip title", () => {
    render(<ReleaseBadge status="quarantined" />);
    expect(screen.getByText("Quarantined")).toHaveAttribute(
      "title",
      expect.stringMatching(/publication is locked/i),
    );
  });
});

describe("StatusDot", () => {
  it("is hidden from assistive tech without a label", () => {
    const { container } = render(<StatusDot tone="success" />);
    expect(container.firstChild).toHaveAttribute("aria-hidden", "true");
  });

  it("is announced when given a label", () => {
    render(<StatusDot tone="danger" label="Failed" />);
    expect(screen.getByRole("img", { name: "Failed" })).toBeInTheDocument();
  });
});
