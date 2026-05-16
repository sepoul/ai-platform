import { NextResponse } from "next/server";
import katex from "katex";

/**
 * LaTeX validation service for backend agents.
 *
 * Two modes (selected by `mode`):
 *
 * - `"inline"` / `"block"` — `latex` is a bare math expression; pass
 *   it straight to KaTeX with the matching `displayMode`.
 * - `"document"` (default) — `latex` is mixed prose + LaTeX, with
 *   `\(...\)` for inline and `\[...\]` for block math. The route
 *   splits on those delimiters and validates each math segment in
 *   isolation; prose is ignored. Returns the first failing segment
 *   with its index so the agent can locate the issue. This is what
 *   the `validate_latex` tool sends after the agent generates a full
 *   markdown answer.
 *
 * Response: `{ valid: true }` or
 * `{ valid: false, error, segment?, segment_index? }`.
 */

interface RequestBody {
  latex?: string;
  mode?: "inline" | "block" | "document";
}

const SEGMENT_RE = /\\\((.+?)\\\)|\\\[([\s\S]+?)\\\]/g;

interface MathSegment {
  value: string;
  displayMode: boolean;
}

function extractMathSegments(source: string): MathSegment[] {
  const out: MathSegment[] = [];
  for (const match of source.matchAll(SEGMENT_RE)) {
    if (match[1] !== undefined) {
      out.push({ value: match[1], displayMode: false });
    } else if (match[2] !== undefined) {
      out.push({ value: match[2], displayMode: true });
    }
  }
  return out;
}

function tryRender(value: string, displayMode: boolean): string | null {
  try {
    katex.renderToString(value, {
      displayMode,
      throwOnError: true,
      strict: "error",
    });
    return null;
  } catch (err) {
    return err instanceof Error ? err.message : "KaTeX failed to parse the input";
  }
}

export async function POST(request: Request) {
  let body: RequestBody;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { valid: false, error: "Invalid JSON body" },
      { status: 400 }
    );
  }

  const latex = typeof body.latex === "string" ? body.latex : null;
  if (!latex) {
    return NextResponse.json(
      { valid: false, error: "Missing `latex` field" },
      { status: 400 }
    );
  }

  const mode = body.mode ?? "document";

  if (mode === "inline" || mode === "block") {
    const error = tryRender(latex, mode === "block");
    return NextResponse.json(error == null ? { valid: true } : { valid: false, error });
  }

  // document mode — split and validate every math segment.
  const segments = extractMathSegments(latex);
  if (segments.length === 0) {
    // No delimiters at all. We accept this as valid: a markdown
    // document with no math is trivially well-formed.
    return NextResponse.json({ valid: true });
  }

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const error = tryRender(seg.value, seg.displayMode);
    if (error != null) {
      return NextResponse.json({
        valid: false,
        error,
        segment: seg.value,
        segment_index: i,
      });
    }
  }

  return NextResponse.json({ valid: true });
}
