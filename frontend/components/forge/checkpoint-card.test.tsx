import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CHECKPOINT } from "@/lib/fixtures";
import { CheckpointCard } from "./checkpoint-card";

describe("CheckpointCard", () => {
  it("approves once and then resolves", async () => {
    const onApprove = vi.fn();
    render(<CheckpointCard checkpoint={CHECKPOINT} onApprove={onApprove} />);

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText(/approved\. the build continues/i)).toBeInTheDocument();
  });

  it("requires a note before sending changes", async () => {
    const onRequestChanges = vi.fn();
    render(<CheckpointCard checkpoint={CHECKPOINT} onRequestChanges={onRequestChanges} />);

    await userEvent.click(screen.getByRole("button", { name: "Request changes" }));
    const send = screen.getByRole("button", { name: "Send changes" });
    expect(send).toBeDisabled();

    await userEvent.type(screen.getByRole("textbox"), "Add Stripe billing");
    await userEvent.click(send);

    expect(onRequestChanges).toHaveBeenCalledWith("Add Stripe billing");
    expect(screen.getByText("Add Stripe billing")).toBeInTheDocument();
  });
});
