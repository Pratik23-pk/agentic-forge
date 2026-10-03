/**
 * Enforces the design brief (docs/frontend/phase-1-design-system.md) on
 * every source file we own or vendor. Failing here means a banned pattern
 * crept in; fix the source rather than loosening the rule.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const SCANNED = ["app", "components", "lib"];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

const files = SCANNED.flatMap((dir) => sourceFiles(join(ROOT, dir))).map((path) => ({
  path: relative(ROOT, path),
  source: readFileSync(path, "utf8"),
}));

const RULES: Array<{ name: string; pattern: RegExp }> = [
  { name: "transition-all (name exact properties)", pattern: /\btransition-all\b/ },
  { name: "ease-in (UI never eases in)", pattern: /\bease-in\b(?!-out)/ },
  {
    name: "raw palette colour (use semantic tokens)",
    pattern:
      /\b(?:bg|text|border|ring|fill|stroke|from|to|via|outline|decoration)-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-\d{2,3}\b/,
  },
  { name: "gradient", pattern: /\b(?:bg-gradient|bg-linear|bg-radial|bg-conic)-/ },
  { name: "large shadow", pattern: /\bshadow-(?:lg|xl|2xl)\b/ },
  { name: "backdrop blur", pattern: /\bbackdrop-blur/ },
  { name: "scale(0) entrance", pattern: /\bscale-0\b|zoom-in-0\b/ },
];

describe("design rules", () => {
  it("scans a meaningful number of files", () => {
    expect(files.length).toBeGreaterThan(20);
  });

  for (const rule of RULES) {
    it(`has no ${rule.name}`, () => {
      const offenders = files
        .filter(({ source }) => rule.pattern.test(source))
        .map(({ path }) => path);
      expect(offenders).toEqual([]);
    });
  }
});
