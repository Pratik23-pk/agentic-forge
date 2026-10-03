"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCode2Icon, SaveIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { ProjectFiles } from "@/components/forge/project-files";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import type { JobPart } from "@/lib/contract";
import { ApiError, ConflictError, listFiles, queryKeys, readFile, writeFile } from "@/lib/studio/api";
import { editorLanguage, isEditableFile } from "@/lib/studio/language";
import { sha256Hex } from "@/lib/studio/sha256";

const CodeEditor = dynamic(() => import("./code-editor"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col gap-2 p-4" aria-hidden="true">
      <Skeleton className="h-3.5 w-2/3" />
      <Skeleton className="h-3.5 w-1/2" />
      <Skeleton className="h-3.5 w-3/5" />
    </div>
  ),
});

function defaultFile(paths: string[]): string | undefined {
  return (
    paths.find((path) => /(^|\/)src\/App\.(t|j)sx?$/.test(path)) ??
    paths.find((path) => /(^|\/)app\/page\.(t|j)sx$/.test(path)) ??
    paths.find((path) => /(^|\/)README\.md$/i.test(path)) ??
    paths.find(isEditableFile)
  );
}

interface CodeTabProps {
  jobId: string | undefined;
  job: JobPart | undefined;
  streamFiles: string[];
  openRequest: { path: string; id: number } | undefined;
}

export function CodeTab({ jobId, job, streamFiles, openRequest }: CodeTabProps) {
  const queryClient = useQueryClient();
  const ready = Boolean(jobId && job?.artifactsReady);

  const listing = useQuery({
    queryKey: queryKeys.files(jobId ?? ""),
    queryFn: () => listFiles(jobId!),
    enabled: ready,
  });
  const paths = ready ? (listing.data?.files.map((file) => file.path) ?? []) : streamFiles;
  const [chosen, setChosen] = useState<string>();
  const selected = chosen && paths.includes(chosen) ? chosen : defaultFile(paths);
  const editable = Boolean(selected && isEditableFile(selected));

  const content = useQuery({
    queryKey: queryKeys.file(jobId ?? "", selected ?? ""),
    queryFn: () => readFile(jobId!, selected!),
    enabled: ready && editable,
    staleTime: Number.POSITIVE_INFINITY,
  });

  // The draft belongs to one file; switching files never carries it over.
  const [draft, setDraft] = useState<{ path: string; text: string } | null>(null);
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ currentSha256: string } | null>(null);
  const dirty = Boolean(draft && draft.path === selected && content.data !== undefined && draft.text !== content.data);

  const save = useMutation({
    mutationFn: async ({ force }: { force?: string } = {}) => {
      if (!jobId || !selected || !draft || content.data === undefined) return null;
      const expected = force ?? (await sha256Hex(content.data));
      await writeFile(jobId, selected, draft.text, expected);
      return { path: selected, text: draft.text };
    },
    onSuccess: (saved) => {
      if (!saved || !jobId) return;
      queryClient.setQueryData(queryKeys.file(jobId, saved.path), saved.text);
      void queryClient.invalidateQueries({ queryKey: queryKeys.files(jobId) });
      // Keep anything typed while the save was in flight.
      setDraft((current) => (current && current.path === saved.path && current.text === saved.text ? null : current));
      setConflict(null);
      toast.success("Saved", { description: "Restart the preview if it does not pick up the change." });
    },
    onError: (error) => {
      if (error instanceof ConflictError) {
        setConflict({ currentSha256: error.currentSha256 });
        return;
      }
      toast.error("Not saved", { description: (error as ApiError).message });
    },
  });

  const { mutate: saveMutate, isPending: saving } = save;
  const handleSave = useCallback(() => {
    if (dirty && !saving) saveMutate({});
  }, [dirty, saving, saveMutate]);

  function requestOpen(path: string) {
    if (path === selected) return;
    if (dirty) setPendingPath(path);
    else setChosen(path);
  }

  // Requests from the chat go through the same guard as clicks in the tree.
  const [handledRequest, setHandledRequest] = useState(openRequest?.id);
  if (openRequest && openRequest.id !== handledRequest) {
    setHandledRequest(openRequest.id);
    if (openRequest.path !== selected) {
      if (dirty) setPendingPath(openRequest.path);
      else setChosen(openRequest.path);
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(200px,260px)_1fr]">
      <div className="min-h-0 overflow-auto border-r p-2">
        {paths.length ? (
          <ProjectFiles paths={paths} selectedPath={selected} onSelect={requestOpen} className="border-0 bg-transparent" />
        ) : (
          <p className="p-2 text-xs text-subtle-foreground">Files appear as the workers write them.</p>
        )}
      </div>

      <div className="flex min-h-0 min-w-0 flex-col">
        {selected ? (
          <div className="flex h-10 shrink-0 items-center gap-2 border-b px-3">
            <FileCode2Icon className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground" title={selected}>
              {selected}
            </span>
            {dirty ? (
              <span className="flex items-center gap-1.5 text-xs text-warning">
                <span className="size-1.5 rounded-full bg-warning" aria-hidden="true" />
                Unsaved
              </span>
            ) : null}
            <Button size="sm" variant="ghost" disabled={!dirty || saving} onClick={handleSave}>
              {saving ? <Spinner data-icon="inline-start" /> : <SaveIcon data-icon="inline-start" />}
              Save
              <Kbd className="ml-1">⌘S</Kbd>
            </Button>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-hidden">
          {!ready ? (
            <Empty className="h-full">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileCode2Icon />
                </EmptyMedia>
                <EmptyTitle>Files are still being written</EmptyTitle>
                <EmptyDescription>You can open and edit them once the build saves the project.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : !selected ? null : !editable ? (
            <p className="p-4 text-[13px] text-muted-foreground">
              This is a binary file. Download the ZIP to inspect it.
            </p>
          ) : content.isError ? (
            <p className="p-4 text-[13px] text-muted-foreground">{(content.error as Error).message}</p>
          ) : content.data === undefined ? null : (
            <CodeEditor
              key={selected}
              value={draft?.path === selected ? draft.text : content.data}
              language={editorLanguage(selected)}
              onChange={(text) => setDraft({ path: selected, text })}
              onSave={handleSave}
              label={`Editing ${selected}`}
            />
          )}
        </div>
      </div>

      <AlertDialog open={pendingPath !== null} onOpenChange={(open) => !open && setPendingPath(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Your edits to {selected} have not been saved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setDraft(null);
                if (pendingPath) setChosen(pendingPath);
                setPendingPath(null);
              }}
            >
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={conflict !== null} onOpenChange={(open) => !open && setConflict(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>This file changed since you opened it</AlertDialogTitle>
            <AlertDialogDescription>
              Someone else saved {selected}. Load their version, or overwrite it with yours.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                setDraft(null);
                if (jobId && selected) void queryClient.invalidateQueries({ queryKey: queryKeys.file(jobId, selected) });
              }}
            >
              Load their version
            </AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => conflict && save.mutate({ force: conflict.currentSha256 })}
            >
              Overwrite
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
