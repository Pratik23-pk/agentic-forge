export interface ErrorSummary {
  summary: string;
  /** The full original text, when the summary leaves something out. */
  details: string | undefined;
}

const KNOWN: Array<{ pattern: RegExp; summary: string }> = [
  {
    pattern: /from lock file|npm ci can only install|lockfile/i,
    summary: "Installing the app's dependencies failed: the lockfile does not match package.json.",
  },
  { pattern: /ERESOLVE|peer dep/i, summary: "Installing the app's dependencies failed: conflicting package versions." },
  { pattern: /Docker is unavailable|Cannot connect to the Docker daemon/i, summary: "Docker is not running. Start Docker Desktop and try again." },
  { pattern: /EADDRINUSE|address already in use/i, summary: "A port the app needs is already in use." },
];

const MAX = 160;

/** Turns raw tool output into one readable line, keeping the original for "details". */
export function summarizeError(raw: string): ErrorSummary {
  const text = raw.trim();
  const known = KNOWN.find(({ pattern }) => pattern.test(text));
  if (known) return { summary: known.summary, details: text };

  const firstLine = text.split("\n")[0].trim();
  const summary = firstLine.length > MAX ? `${firstLine.slice(0, MAX)}…` : firstLine;
  return { summary, details: summary === text ? undefined : text };
}
