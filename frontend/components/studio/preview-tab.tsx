"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRightIcon,
  MonitorIcon,
  PlayIcon,
  RotateCwIcon,
  ShieldAlertIcon,
  SmartphoneIcon,
  SquareIcon,
  TabletIcon,
  TerminalSquareIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Terminal } from "@/components/ai-elements/terminal";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { JobPart } from "@/lib/contract";
import { getPreview, previewLogs, queryKeys, startPreview, stopPreview } from "@/lib/studio/api";
import { cn } from "@/lib/utils";

const DEVICE_WIDTH = {
  desktop: "w-full",
  tablet: "w-[768px] max-w-full",
  mobile: "w-[390px] max-w-full",
} as const;

type Device = keyof typeof DEVICE_WIDTH;

const READY_STATUSES = new Set(["succeeded", "failed", "blocked", "awaiting_human_feedback"]);

/** Mounted only while starting, so its timer begins at zero on every start. */
function StartingState() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center" role="status">
      <div className="flex items-center gap-2 text-[13px]">
        <Spinner className="text-muted-foreground" />
        Starting the sandbox
        <span className="tabular text-subtle-foreground">{elapsed}s</span>
      </div>
      <p className="max-w-72 text-xs text-subtle-foreground">
        The first start builds a container and installs dependencies, which can take a few minutes.
      </p>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  children,
  disabled,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label={label} onClick={onClick} disabled={disabled}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function PreviewLogs({ jobId }: { jobId: string }) {
  const logs = useQuery({ queryKey: ["preview-logs", jobId], queryFn: () => previewLogs(jobId) });
  return (
    <div className="flex max-h-56 min-h-0 flex-col border-t">
      <Terminal
        output={logs.data ?? (logs.isPending ? "Loading logs…" : "No logs yet.")}
        className="rounded-none border-0 bg-card"
      />
    </div>
  );
}

export function PreviewTab({ jobId, job }: { jobId: string | undefined; job: JobPart | undefined }) {
  const queryClient = useQueryClient();
  const ready = Boolean(jobId && job?.artifactsReady && READY_STATUSES.has(job.status));
  const [device, setDevice] = useState<Device>("desktop");
  const [frameKey, setFrameKey] = useState(0);
  const [showLogs, setShowLogs] = useState(false);
  const autoStarted = useRef(false);

  const preview = useQuery({
    queryKey: queryKeys.preview(jobId ?? ""),
    queryFn: () => getPreview(jobId!),
    enabled: ready,
    refetchInterval: (query) => (query.state.data?.status === "starting" ? 2000 : false),
  });

  const start = useMutation({
    mutationFn: () => startPreview(jobId!),
    onSuccess: (record) => queryClient.setQueryData(queryKeys.preview(jobId!), record),
  });

  const stop = useMutation({
    mutationFn: () => stopPreview(jobId!),
    onSuccess: (record) => queryClient.setQueryData(queryKeys.preview(jobId!), record),
  });

  const { mutate: startMutate } = start;
  useEffect(() => {
    if (ready && preview.isSuccess && preview.data === null && !autoStarted.current) {
      autoStarted.current = true;
      startMutate();
    }
  }, [ready, preview.isSuccess, preview.data, startMutate]);

  const starting = start.isPending || preview.data?.status === "starting";
  const record = preview.data;
  const service = record?.services.find((item) => item.name === "frontend") ?? record?.services[0];
  const failure = start.error?.message ?? (record?.status === "failed" ? record.error : null);

  if (!jobId || !ready) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MonitorIcon />
          </EmptyMedia>
          <EmptyTitle>No preview yet</EmptyTitle>
          <EmptyDescription>
            {job && !job.artifactsReady && READY_STATUSES.has(job.status) && job.status !== "awaiting_human_feedback"
              ? "This build did not produce runnable files."
              : "The app runs here once the build writes the project."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (starting) return <StartingState />;

  if (failure || !record || record.status !== "running" || !service) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex flex-1 items-center justify-center p-6">
          {failure ? (
            <Alert variant="destructive" className="max-w-md">
              <AlertTitle>The preview could not start</AlertTitle>
              <AlertDescription>
                <p className="break-words">{failure}</p>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => start.mutate()}>
                    Try again
                  </Button>
                  {record ? (
                    <Button size="sm" variant="ghost" onClick={() => setShowLogs((open) => !open)}>
                      {showLogs ? "Hide logs" : "View logs"}
                    </Button>
                  ) : null}
                </div>
              </AlertDescription>
            </Alert>
          ) : (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <PlayIcon />
                </EmptyMedia>
                <EmptyTitle>Preview stopped</EmptyTitle>
                <EmptyDescription>Start the sandbox to run the generated app.</EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button size="sm" onClick={() => start.mutate()}>
                  <PlayIcon data-icon="inline-start" />
                  Start preview
                </Button>
              </EmptyContent>
            </Empty>
          )}
        </div>
        {showLogs && record ? <PreviewLogs jobId={jobId} /> : null}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b px-2">
        <IconButton label="Reload" onClick={() => setFrameKey((key) => key + 1)}>
          <RotateCwIcon />
        </IconButton>
        <div className="mx-1 min-w-0 flex-1 truncate rounded-md border bg-background px-2.5 py-1 font-mono text-xs text-muted-foreground">
          {service.url}
        </div>
        <ToggleGroup
          type="single"
          size="sm"
          value={device}
          onValueChange={(value) => value && setDevice(value as Device)}
          aria-label="Preview size"
        >
          <ToggleGroupItem value="desktop" aria-label="Desktop">
            <MonitorIcon />
          </ToggleGroupItem>
          <ToggleGroupItem value="tablet" aria-label="Tablet">
            <TabletIcon />
          </ToggleGroupItem>
          <ToggleGroupItem value="mobile" aria-label="Mobile">
            <SmartphoneIcon />
          </ToggleGroupItem>
        </ToggleGroup>
        <IconButton label={showLogs ? "Hide logs" : "Show logs"} onClick={() => setShowLogs((open) => !open)}>
          <TerminalSquareIcon />
        </IconButton>
        <IconButton label="Open in new tab" onClick={() => window.open(service.url, "_blank", "noopener")}>
          <ArrowUpRightIcon />
        </IconButton>
        <IconButton label="Stop preview" onClick={() => stop.mutate()} disabled={stop.isPending}>
          <SquareIcon />
        </IconButton>
      </div>

      {record.quarantined ? (
        <div className="flex items-center gap-2 border-b bg-danger/5 px-3 py-1.5 text-xs text-danger">
          <ShieldAlertIcon className="size-3.5" aria-hidden="true" />
          Isolated preview: this build has blocking security findings, so it runs without network access.
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 justify-center bg-background">
        <div
          className={cn(
            "h-full transition-[width] duration-200 ease-in-out motion-reduce:transition-none",
            DEVICE_WIDTH[device],
            device !== "desktop" && "border-x",
          )}
        >
          <iframe
            key={frameKey}
            src={service.url}
            title="Generated app preview"
            // The sandbox URL is a different origin (127.0.0.1:<port>), so these
            // permissions do not grant access to the studio.
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            referrerPolicy="no-referrer"
            className="size-full bg-white"
          />
        </div>
      </div>

      {showLogs ? <PreviewLogs jobId={jobId} /> : null}
    </div>
  );
}
