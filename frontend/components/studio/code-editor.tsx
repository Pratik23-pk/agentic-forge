"use client";

import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { sql } from "@codemirror/lang-sql";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import type { Extension } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo } from "react";

import type { EditorLanguage } from "@/lib/studio/language";

// Matches the Vesper palette used by read-only code blocks.
const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.operatorKeyword, tags.modifier, tags.controlKeyword], color: "#a0a0a0" },
  { tag: [tags.string, tags.special(tags.string), tags.regexp], color: "#99ffe4" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.typeName, tags.className, tags.tagName], color: "#ffc799" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "#ffc799" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "#6b6b6b", fontStyle: "italic" },
  { tag: [tags.propertyName, tags.attributeName], color: "#d4d4d4" },
  { tag: [tags.heading], color: "#ffc799", fontWeight: "600" },
  { tag: [tags.link, tags.url], color: "#99ffe4", textDecoration: "underline" },
  { tag: tags.invalid, color: "var(--danger)" },
]);

const theme = EditorView.theme(
  {
    "&": {
      height: "100%",
      backgroundColor: "var(--background)",
      color: "var(--foreground)",
      fontSize: "13px",
    },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.6" },
    ".cm-content": { caretColor: "var(--brand)", padding: "12px 0" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--brand)" },
    ".cm-gutters": {
      backgroundColor: "var(--background)",
      color: "var(--subtle-foreground)",
      border: "none",
    },
    ".cm-lineNumbers .cm-gutterElement": { padding: "0 12px 0 16px" },
    ".cm-activeLine": { backgroundColor: "oklch(1 0 0 / 0.03)" },
    ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--muted-foreground)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
      backgroundColor: "oklch(0.76 0.13 64 / 0.22) !important",
    },
    ".cm-matchingBracket": { backgroundColor: "oklch(1 0 0 / 0.08)", outline: "none" },
    ".cm-foldGutter .cm-gutterElement": { color: "var(--subtle-foreground)" },
  },
  { dark: true },
);

function languageExtension(language: EditorLanguage): Extension[] {
  switch (language) {
    case "tsx":
      return [javascript({ jsx: true, typescript: true })];
    case "typescript":
      return [javascript({ typescript: true })];
    case "jsx":
      return [javascript({ jsx: true })];
    case "javascript":
      return [javascript()];
    case "python":
      return [python()];
    case "css":
      return [css()];
    case "html":
      return [html()];
    case "json":
      return [json()];
    case "markdown":
      return [markdown()];
    case "sql":
      return [sql()];
    default:
      return [];
  }
}

interface CodeEditorProps {
  value: string;
  language: EditorLanguage;
  onChange: (value: string) => void;
  onSave: () => void;
  readOnly?: boolean;
  label: string;
}

export default function CodeEditor({ value, language, onChange, onSave, readOnly, label }: CodeEditorProps) {
  const extensions = useMemo(
    () => [
      ...languageExtension(language),
      theme,
      syntaxHighlighting(highlight),
      keymap.of([
        {
          key: "Mod-s",
          preventDefault: true,
          run: () => {
            onSave();
            return true;
          },
        },
      ]),
      EditorView.contentAttributes.of({ "aria-label": label }),
    ],
    [language, onSave, label],
  );

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      readOnly={readOnly}
      theme="none"
      height="100%"
      className="h-full"
      basicSetup={{ highlightActiveLine: !readOnly, foldGutter: true, autocompletion: false }}
    />
  );
}
