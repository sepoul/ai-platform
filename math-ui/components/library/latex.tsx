"use client";

import { useMemo } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { cn } from "@/lib/utils";

/**
 * Renders mixed prose + LaTeX. Recognises KaTeX-style delimiters:
 *
 *   \(...\)   inline math
 *   \[...\]   block math
 *
 * Each segment is split out and rendered through KaTeX
 * (`renderToString`); plain prose stays untouched. Invalid math falls
 * back to the raw source in red rather than throwing — the validated
 * artifact path won't hit this, but unvalidated draft inputs might.
 *
 * The companion validation endpoint is `/api/tools/validate-latex`,
 * which uses the same library to give the agent pre-render feedback.
 */

type Segment =
  | { kind: "prose"; value: string }
  | { kind: "inline"; value: string }
  | { kind: "block"; value: string };

const SEGMENT_RE = /\\\((.+?)\\\)|\\\[([\s\S]+?)\\\]/g;

function splitSegments(source: string): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;
  for (const match of source.matchAll(SEGMENT_RE)) {
    const start = match.index ?? 0;
    if (start > cursor) {
      out.push({ kind: "prose", value: source.slice(cursor, start) });
    }
    if (match[1] !== undefined) {
      out.push({ kind: "inline", value: match[1] });
    } else if (match[2] !== undefined) {
      out.push({ kind: "block", value: match[2] });
    }
    cursor = start + match[0].length;
  }
  if (cursor < source.length) {
    out.push({ kind: "prose", value: source.slice(cursor) });
  }
  return out;
}

function renderMath(value: string, displayMode: boolean): string {
  try {
    return katex.renderToString(value, {
      displayMode,
      throwOnError: false,
      strict: "ignore",
      output: "html",
    });
  } catch {
    return `<span class="text-destructive">${escape(value)}</span>`;
  }
}

function escape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function Latex({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  const segments = useMemo(() => splitSegments(children), [children]);
  return (
    <div className={cn("text-sm leading-relaxed", className)}>
      {segments.map((seg, i) => {
        if (seg.kind === "prose") {
          // Preserve newlines in prose so the agent's paragraphing
          // survives without us pulling in a markdown layer here.
          return (
            <span key={i} style={{ whiteSpace: "pre-wrap" }}>
              {seg.value}
            </span>
          );
        }
        const html = renderMath(seg.value, seg.kind === "block");
        const Tag = seg.kind === "block" ? "div" : "span";
        return (
          <Tag
            key={i}
            className={seg.kind === "block" ? "my-2 overflow-x-auto" : ""}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        );
      })}
    </div>
  );
}
