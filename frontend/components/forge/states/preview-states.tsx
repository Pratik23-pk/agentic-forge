"use client";

import {
  ArrowUpRightIcon,
  MonitorIcon,
  RotateCwIcon,
  SmartphoneIcon,
  TabletIcon,
} from "lucide-react";
import { useState } from "react";

import { Terminal } from "@/components/ai-elements/terminal";
import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewNavigationButton,
  WebPreviewUrl,
} from "@/components/ai-elements/web-preview";
import { StatusDot } from "@/components/forge/status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { PREVIEW_LOGS } from "@/lib/fixtures";
import { GENERATED_APP_MOCK } from "@/lib/preview-mock";
import { cn } from "@/lib/utils";
import { Section, Specimen } from "./section";

const PREVIEW_URL = "http://127.0.0.1:41873/";

const DEVICE_WIDTH = {
  desktop: "w-full",
  tablet: "w-[768px] max-w-full",
  mobile: "w-[390px] max-w-full",
} as const;

type Device = keyof typeof DEVICE_WIDTH;

export function PreviewFrame({ className }: { className?: string }) {
  const [device, setDevice] = useState<Device>("desktop");

  return (
    <WebPreview defaultUrl={PREVIEW_URL} className={cn("overflow-hidden", className)}>
      <WebPreviewNavigation className="gap-1.5 border-b p-1.5">
        <WebPreviewNavigationButton tooltip="Reload">
          <RotateCwIcon />
        </WebPreviewNavigationButton>
        <WebPreviewUrl className="h-7 font-mono text-xs md:text-xs" readOnly />
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
        <WebPreviewNavigationButton tooltip="Open in new tab">
          <ArrowUpRightIcon />
        </WebPreviewNavigationButton>
      </WebPreviewNavigation>
      <div className="flex flex-1 justify-center bg-background">
        <div className={cn("flex flex-col transition-[width] duration-200 ease-in-out", DEVICE_WIDTH[device])}>
          {/* srcDoc inherits the studio origin, so the static mock gets no sandbox permissions at all. */}
          <WebPreviewBody sandbox="" srcDoc={GENERATED_APP_MOCK} title="Roastery Portal preview" />
        </div>
      </div>
    </WebPreview>
  );
}

const START_STEPS = [
  { label: "Build image", state: "done" },
  { label: "Install dependencies", state: "running" },
  { label: "Start services", state: "queued" },
  { label: "Browser check", state: "queued" },
] as const;

function StartingState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 p-6">
      <div className="flex items-center gap-2 text-[13px]">
        <Spinner className="text-muted-foreground" />
        Starting the sandbox
      </div>
      <ol className="flex w-56 flex-col gap-1.5">
        {START_STEPS.map((step) => (
          <li key={step.label} className="flex items-center gap-2.5 text-xs">
            <StatusDot
              tone={step.state === "done" ? "success" : step.state === "running" ? "brand" : "neutral"}
              live={step.state === "running"}
            />
            <span className={step.state === "queued" ? "text-subtle-foreground" : "text-muted-foreground"}>
              {step.label}
            </span>
          </li>
        ))}
      </ol>
      <p className="max-w-64 text-center text-xs text-subtle-foreground">
        First starts take a few minutes while the container builds.
      </p>
    </div>
  );
}

function FailedState() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Alert variant="destructive" className="max-w-sm">
        <AlertTitle>The preview could not start</AlertTitle>
        <AlertDescription>
          <p>The backend service exited during startup: missing DATABASE_URL.</p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="secondary">
              Retry
            </Button>
            <Button size="sm" variant="ghost">
              View logs
            </Button>
          </div>
        </AlertDescription>
      </Alert>
    </div>
  );
}

export function PreviewStates() {
  return (
    <Section
      id="preview"
      title="Preview"
      description="The generated app runs in the sandbox and renders here. Starting takes minutes, so the frame says what it is doing; failures say why and what to do next."
    >
      <Specimen label="Running · resize with the device toggle" className="p-0">
        <PreviewFrame className="h-[420px] rounded-xl border-0" />
      </Specimen>
      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Starting" className="h-72 p-0">
          <StartingState />
        </Specimen>
        <Specimen label="Failed" className="h-72 p-0">
          <FailedState />
        </Specimen>
      </div>
      <Specimen label="Runtime logs" className="rounded-none border-0 bg-transparent p-0">
        <Terminal output={PREVIEW_LOGS} className="max-h-64 bg-card" />
      </Specimen>
    </Section>
  );
}
