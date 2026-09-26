import { describe, expect, it } from "vitest";

import { buildFileTree } from "./file-tree";

describe("buildFileTree", () => {
  it("nests files under their folders", () => {
    const tree = buildFileTree(["src/App.tsx", "src/lib/dates.ts", "README.md"]);
    expect(tree).toEqual([
      {
        kind: "folder",
        name: "src",
        path: "src",
        children: [
          {
            kind: "folder",
            name: "lib",
            path: "src/lib",
            children: [{ kind: "file", name: "dates.ts", path: "src/lib/dates.ts" }],
          },
          { kind: "file", name: "App.tsx", path: "src/App.tsx" },
        ],
      },
      { kind: "file", name: "README.md", path: "README.md" },
    ]);
  });

  it("sorts folders before files, then by name", () => {
    const tree = buildFileTree(["b.ts", "a/x.ts", "A.ts", "c/y.ts"]);
    expect(tree.map((node) => node.name)).toEqual(["a", "c", "A.ts", "b.ts"]);
  });

  it("ignores empty segments and duplicate paths", () => {
    const tree = buildFileTree(["/src//App.tsx", "src/App.tsx"]);
    expect(tree).toHaveLength(1);
    expect(tree[0]).toMatchObject({ kind: "folder", path: "src" });
    expect(tree[0].kind === "folder" && tree[0].children).toHaveLength(1);
  });

  it("returns an empty tree for no paths", () => {
    expect(buildFileTree([])).toEqual([]);
  });
});
