"use client";

import { RotateCcwIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { StageList } from "@/components/forge/stage-list";
import { STAGES_BUILDING } from "@/lib/fixtures";
import { Specimen } from "./section";

const CURVES = [
  { name: "ease-out", value: "cubic-bezier(0.23, 1, 0.32, 1)", use: "Enter, press, popovers" },
  { name: "ease-in-out", value: "cubic-bezier(0.77, 0, 0.175, 1)", use: "Movement on screen" },
  { name: "ease-drawer", value: "cubic-bezier(0.32, 0.72, 0, 1)", use: "Sheets and drawers" },
];

const DURATIONS = [
  { name: "Press", value: "150ms" },
  { name: "Tooltip, popover", value: "150ms in · 100ms out" },
  { name: "Dialog", value: "200ms in · 150ms out" },
  { name: "Stream entry", value: "180ms, 40ms stagger" },
];

export function MotionDemo() {
  const [replay, setReplay] = useState(0);

  return (
    <div className="grid gap-10 md:grid-cols-2">
      <Specimen label="Motion · curves and timing">
        <dl className="flex flex-col gap-3">
          {CURVES.map((curve) => (
            <div key={curve.name} className="flex flex-col gap-0.5">
              <dt className="flex items-baseline justify-between gap-4">
                <span className="font-mono text-xs">{curve.name}</span>
                <span className="text-xs text-subtle-foreground">{curve.use}</span>
              </dt>
              <dd className="font-mono text-xs text-muted-foreground">{curve.value}</dd>
            </div>
          ))}
        </dl>
        <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-2 border-t pt-4">
          {DURATIONS.map((duration) => (
            <div key={duration.name} className="contents">
              <dt className="text-xs text-muted-foreground">{duration.name}</dt>
              <dd className="tabular text-right font-mono text-xs">{duration.value}</dd>
            </div>
          ))}
        </dl>
      </Specimen>
      <Specimen label="Motion · stream entry">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs text-muted-foreground">New stages rise 4px and fade in.</p>
          <Button variant="ghost" size="sm" onClick={() => setReplay((count) => count + 1)}>
            <RotateCcwIcon data-icon="inline-start" />
            Replay
          </Button>
        </div>
        <StageList key={replay} stages={STAGES_BUILDING.slice(0, 5)} />
      </Specimen>
    </div>
  );
}
