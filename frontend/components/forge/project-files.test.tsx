import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectFiles } from "./project-files";

describe("ProjectFiles", () => {
  it("selects files but never folders", async () => {
    const onSelect = vi.fn();
    render(<ProjectFiles paths={["src/App.tsx"]} onSelect={onSelect} />);

    await userEvent.click(screen.getByText("App.tsx"));
    expect(onSelect).toHaveBeenCalledWith("src/App.tsx");

    await userEvent.click(screen.getByRole("button", { name: "src" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("collapses a folder when its name is clicked", async () => {
    render(<ProjectFiles paths={["src/App.tsx"]} />);
    const folder = screen.getByRole("button", { name: "src" });

    expect(folder).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(folder);
    expect(folder).toHaveAttribute("aria-expanded", "false");
  });

  it("expands folders that arrive later but keeps user collapses", async () => {
    const { rerender } = render(<ProjectFiles paths={["src/App.tsx"]} />);
    await userEvent.click(screen.getByRole("button", { name: "src" }));

    rerender(<ProjectFiles paths={["src/App.tsx", "api/main.py"]} />);

    expect(screen.getByRole("button", { name: "src" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "api" })).toHaveAttribute("aria-expanded", "true");
  });

  it("labels the tree", () => {
    render(<ProjectFiles paths={["README.md"]} />);
    expect(screen.getByRole("tree", { name: "Project files" })).toBeInTheDocument();
  });
});
