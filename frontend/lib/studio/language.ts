export type EditorLanguage =
  | "tsx"
  | "typescript"
  | "jsx"
  | "javascript"
  | "python"
  | "css"
  | "html"
  | "json"
  | "markdown"
  | "sql"
  | "text";

const BY_EXTENSION: Record<string, EditorLanguage> = {
  tsx: "tsx",
  ts: "typescript",
  mts: "typescript",
  cts: "typescript",
  jsx: "jsx",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  css: "css",
  scss: "css",
  html: "html",
  json: "json",
  md: "markdown",
  mdx: "markdown",
  sql: "sql",
};

const BINARY = /\.(png|jpe?g|gif|webp|avif|ico|bmp|tiff?|woff2?|ttf|otf|eot|mp3|mp4|webm|mov|wav|ogg|zip|gz|tgz|pdf|wasm|so|dylib|exe|pyc|sqlite|db)$/i;

function extension(path: string): string {
  const name = path.split("/").pop() ?? path;
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function editorLanguage(path: string): EditorLanguage {
  return BY_EXTENSION[extension(path)] ?? "text";
}

/** Anything that is not a known binary format opens in the editor. */
export function isEditableFile(path: string): boolean {
  return !BINARY.test(path);
}
