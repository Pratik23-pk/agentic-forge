"use client";

import { FileTree, FileTreeFile, FileTreeFolder } from "@/components/ai-elements/file-tree";
import { buildFileTree, type FileTreeNode } from "@/lib/file-tree";

interface ProjectFilesProps {
  paths: readonly string[];
  selectedPath?: string;
  onSelect?: (path: string) => void;
  className?: string;
}

function allFolderPaths(nodes: FileTreeNode[]): string[] {
  return nodes.flatMap((node) =>
    node.kind === "folder" ? [node.path, ...allFolderPaths(node.children)] : [],
  );
}

function renderNodes(nodes: FileTreeNode[]) {
  return nodes.map((node) =>
    node.kind === "folder" ? (
      <FileTreeFolder key={node.path} path={node.path} name={node.name}>
        {renderNodes(node.children)}
      </FileTreeFolder>
    ) : (
      <FileTreeFile key={node.path} path={node.path} name={node.name} title={node.path} />
    ),
  );
}

/** Generated project files as a tree, expanded by default. */
export function ProjectFiles({ paths, selectedPath, onSelect, className }: ProjectFilesProps) {
  const tree = buildFileTree(paths);
  return (
    <FileTree
      className={className}
      defaultExpanded={new Set(allFolderPaths(tree))}
      selectedPath={selectedPath}
      onSelect={onSelect}
    >
      {renderNodes(tree)}
    </FileTree>
  );
}
