const prefixes = [
  "Aurora Studio",
  "Cobalt Works",
  "Nova Project",
  "Orbit Foundry",
  "Pixel Workshop"
];

export function createReadableProjectName(): string {
  const seed = globalThis.crypto?.getRandomValues
    ? globalThis.crypto.getRandomValues(new Uint32Array(1))[0]
    : Date.now();
  const prefix = prefixes[seed % prefixes.length];
  const suffix = seed.toString(36).toUpperCase().padStart(6, "0").slice(-6);
  return `${prefix} ${suffix}`;
}
