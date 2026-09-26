export type FileTreeNode =
  | { kind: "file"; name: string; path: string }
  | { kind: "folder"; name: string; path: string; children: FileTreeNode[] };

type MutableFolder = { kind: "folder"; name: string; path: string; children: Map<string, MutableNode> };
type MutableNode = { kind: "file"; name: string; path: string } | MutableFolder;

/**
 * Turns flat project paths into a sorted tree: folders first, then files, by
 * name. A filesystem cannot hold a file and a folder at the same path, so if
 * the input contains both (`a` and `a/b.ts`) the folder wins.
 */
export function buildFileTree(paths: readonly string[]): FileTreeNode[] {
  const root: MutableFolder = { kind: "folder", name: "", path: "", children: new Map() };

  for (const rawPath of paths) {
    const segments = rawPath.split("/").filter(Boolean);
    let folder = root;
    segments.forEach((segment, index) => {
      const path = segments.slice(0, index + 1).join("/");
      const isFile = index === segments.length - 1;
      const existing = folder.children.get(segment);
      if (isFile) {
        if (!existing) folder.children.set(segment, { kind: "file", name: segment, path });
        return;
      }
      if (existing?.kind === "folder") {
        folder = existing;
        return;
      }
      const next: MutableFolder = { kind: "folder", name: segment, path, children: new Map() };
      folder.children.set(segment, next);
      folder = next;
    });
  }

  return freeze(root);
}

function freeze(folder: MutableFolder): FileTreeNode[] {
  return [...folder.children.values()]
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name, "en", { numeric: true });
    })
    .map((node) => (node.kind === "file" ? node : { ...node, children: freeze(node) }));
}
