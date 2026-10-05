import { ToneBadge } from "@/components/forge/status";
import { MotionDemo } from "./motion-demo";
import { Section, Specimen } from "./section";

const SURFACES = [
  { token: "background", className: "bg-background", note: "Page" },
  { token: "card", className: "bg-card", note: "Panels" },
  { token: "popover", className: "bg-popover", note: "Overlays" },
  { token: "secondary", className: "bg-secondary", note: "Controls" },
  { token: "accent", className: "bg-accent", note: "Hover" },
];

const TEXT = [
  { token: "foreground", className: "text-foreground", sample: "Primary text" },
  { token: "muted-foreground", className: "text-muted-foreground", sample: "Supporting text" },
  { token: "subtle-foreground", className: "text-subtle-foreground", sample: "Metadata and hints" },
];

const TONES = [
  { tone: "brand", className: "bg-brand", note: "Brand, focus, live work" },
  { tone: "success", className: "bg-success", note: "Passed, verified" },
  { tone: "warning", className: "bg-warning", note: "Needs review, provisional" },
  { tone: "danger", className: "bg-danger", note: "Failed, quarantined" },
  { tone: "info", className: "bg-info", note: "Informational" },
] as const;

const TYPE_SCALE = [
  { name: "Display", className: "text-[28px] leading-9 font-semibold tracking-[-0.02em]", spec: "28 / 36 · 600" },
  { name: "Title", className: "text-xl font-medium tracking-tight", spec: "20 / 28 · 500" },
  { name: "Heading", className: "text-[15px] font-medium", spec: "15 / 22 · 500" },
  { name: "Body", className: "text-sm", spec: "14 / 20 · 400" },
  { name: "Small", className: "text-[13px] text-muted-foreground", spec: "13 / 20 · 400" },
  { name: "Mono", className: "font-mono text-xs text-muted-foreground", spec: "12 / 16 · Geist Mono" },
];

export function Foundations() {
  return (
    <Section
      id="foundations"
      title="Foundations"
      description="Cool neutrals carry the interface. Depth comes from three surface steps and hairline borders. Ember is the only accent and is reserved for the brand, focus and live work."
    >
      <Specimen label="Surfaces" className="p-0">
        <div className="grid grid-cols-2 sm:grid-cols-5">
          {SURFACES.map((surface) => (
            <div key={surface.token} className="border-r border-b p-4 last:border-r-0 sm:border-b-0">
              <div className={`h-14 rounded-md border ${surface.className}`} />
              <p className="mt-3 font-mono text-xs">{surface.token}</p>
              <p className="text-xs text-subtle-foreground">{surface.note}</p>
            </div>
          ))}
        </div>
      </Specimen>

      <div className="grid gap-10 md:grid-cols-2">
        <Specimen label="Text">
          <div className="flex flex-col gap-3">
            {TEXT.map((text) => (
              <div key={text.token} className="flex items-baseline justify-between gap-4">
                <span className={text.className}>{text.sample}</span>
                <span className="font-mono text-xs text-subtle-foreground">{text.token}</span>
              </div>
            ))}
          </div>
        </Specimen>
        <Specimen label="Tones">
          <div className="flex flex-col gap-3">
            {TONES.map((tone) => (
              <div key={tone.tone} className="flex items-center justify-between gap-4">
                <ToneBadge tone={tone.tone}>{tone.tone}</ToneBadge>
                <span className="text-xs text-subtle-foreground">{tone.note}</span>
              </div>
            ))}
          </div>
        </Specimen>
      </div>

      <Specimen label="Type · Geist Sans and Geist Mono">
        <div className="flex flex-col divide-y">
          {TYPE_SCALE.map((step) => (
            <div key={step.name} className="grid grid-cols-[88px_1fr_auto] items-baseline gap-4 py-3 first:pt-0 last:pb-0">
              <span className="text-xs text-subtle-foreground">{step.name}</span>
              <span className={`truncate ${step.className}`}>Ship the portal by Friday</span>
              <span className="tabular hidden font-mono text-xs text-subtle-foreground sm:inline">{step.spec}</span>
            </div>
          ))}
        </div>
      </Specimen>

      <MotionDemo />
    </Section>
  );
}
