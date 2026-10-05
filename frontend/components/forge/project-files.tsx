"use client";

import { useState } from "react";

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

/**
 * Generated project files as a tree. Folders are expanded by default,
 * including folders that stream in later; only folders the user collapsed
 * stay collapsed.
 */
export function ProjectFiles({ paths, selectedPath, onSelect, className }: ProjectFilesProps) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const tree = buildFileTree(paths);
  const folders = allFolderPaths(tree);
  const expanded = new Set(folders.filter((folder) => !collapsed.has(folder)));

  return (
    <FileTree
      aria-label="Project files"
      className={className}
      expanded={expanded}
      onExpandedChange={(next) =>
        setCollapsed(new Set(folders.filter((folder) => !next.has(folder))))
      }
      selectedPath={selectedPath}
      onSelect={onSelect}
    >
      {renderNodes(tree)}
    </FileTree>
  );
}
