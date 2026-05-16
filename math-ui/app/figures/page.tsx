"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Play, Wand2, XCircle } from "lucide-react";
import {
  Figure,
  PageContainer,
  PageHeader,
  Section,
  type FigureSpec,
} from "@/components/library";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/**
 * Live scratchpad for the freeform figure spec the agent emits.
 * Paste JSON, see the renderer's interpretation, click **Validate**
 * to round-trip through `/api/tools/validate-figure`.
 */

const SEED_MANIFOLD: FigureSpec = {
  title: "A coordinate chart on a manifold",
  elements: [
    { type: "blob", at: [0.26, 0.5], size: [0.19, 0.24], seed: 1, label: "M", labelAt: [0.26, 0.18] },
    { type: "blob", at: [0.26, 0.52], size: [0.09, 0.1], seed: 5, dashed: true, label: "U", labelAt: [0.13, 0.52] },
    { type: "rect", at: [0.74, 0.5], size: [0.28, 0.34], grid: true, label: "\\mathbb{R}^n", labelAt: [0.74, 0.16] },
    { type: "blob", at: [0.74, 0.52], size: [0.1, 0.11], seed: 9, dashed: true, label: "\\varphi(U)", labelAt: [0.88, 0.52] },
    { type: "arrow", from: [0.36, 0.5], to: [0.62, 0.5], curve: -0.06, label: "\\varphi" },
  ],
};

const SEED_COMPATIBLE: FigureSpec = {
  title: "Smooth transition between overlapping charts",
  elements: [
    { type: "blob", at: [0.25, 0.5], size: [0.2, 0.28], seed: 2, label: "M", labelAt: [0.25, 0.14] },
    { type: "blob", at: [0.21, 0.46], size: [0.1, 0.11], seed: 7, dashed: true, label: "U", labelAt: [0.1, 0.42] },
    { type: "blob", at: [0.31, 0.55], size: [0.1, 0.11], seed: 11, dashed: true, label: "V", labelAt: [0.42, 0.62] },
    { type: "label", at: [0.26, 0.51], text: "U \\cap V" },
    { type: "rect", at: [0.78, 0.26], size: [0.27, 0.22], grid: true, label: "\\varphi(U)", labelAt: [0.78, 0.1] },
    { type: "rect", at: [0.78, 0.74], size: [0.27, 0.22], grid: true, label: "\\psi(V)", labelAt: [0.78, 0.92] },
    { type: "arrow", from: [0.34, 0.42], to: [0.65, 0.28], curve: -0.05, label: "\\varphi" },
    { type: "arrow", from: [0.41, 0.58], to: [0.65, 0.74], curve: 0.05, label: "\\psi" },
    { type: "arrow", from: [0.86, 0.38], to: [0.86, 0.62], curve: 0.05, label: "\\psi \\circ \\varphi^{-1}" },
  ],
};

const SEED_TORUS: FigureSpec = {
  title: "Torus as a quotient of the square",
  elements: [
    { type: "polygon", points: [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]] },
    { type: "label", at: [0.5, 0.24], text: "a" },
    { type: "label", at: [0.5, 0.76], text: "a" },
    { type: "label", at: [0.24, 0.5], text: "b" },
    { type: "label", at: [0.76, 0.5], text: "b" },
    { type: "arrow", from: [0.4, 0.27], to: [0.6, 0.27] },
    { type: "arrow", from: [0.4, 0.73], to: [0.6, 0.73] },
    { type: "arrow", from: [0.27, 0.4], to: [0.27, 0.6] },
    { type: "arrow", from: [0.73, 0.4], to: [0.73, 0.6] },
  ],
};

interface Example {
  name: string;
  spec: FigureSpec;
}

const EXAMPLES: Example[] = [
  { name: "Manifold chart", spec: SEED_MANIFOLD },
  { name: "Compatible charts", spec: SEED_COMPATIBLE },
  { name: "Torus quotient", spec: SEED_TORUS },
];

interface ValidationState {
  status: "idle" | "checking" | "valid" | "invalid";
  error?: string;
  path?: string;
}

export default function FiguresPlaygroundPage() {
  const [source, setSource] = useState<string>(() =>
    JSON.stringify(SEED_MANIFOLD, null, 2)
  );
  const [validation, setValidation] = useState<ValidationState>({ status: "idle" });

  const parsed = useMemo<{ ok: true; value: FigureSpec } | { ok: false; error: string }>(() => {
    try {
      const value = JSON.parse(source);
      return { ok: true, value };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
  }, [source]);

  const handleValidate = async () => {
    setValidation({ status: "checking" });
    if (!parsed.ok) {
      setValidation({ status: "invalid", error: parsed.error });
      return;
    }
    try {
      const res = await fetch("/api/tools/validate-figure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: parsed.value }),
      });
      const body = (await res.json()) as {
        valid: boolean;
        error?: string;
        path?: string;
      };
      setValidation(
        body.valid
          ? { status: "valid" }
          : {
              status: "invalid",
              error: body.error ?? "spec is not valid",
              path: body.path,
            }
      );
    } catch (err) {
      setValidation({
        status: "invalid",
        error: err instanceof Error ? err.message : "validation request failed",
      });
    }
  };

  return (
    <PageContainer>
      <PageHeader
        title="Figure scratchpad"
        subtitle={
          <>
            Paste a freeform figure spec — the renderer draws whatever
            primitive elements you list, at normalized coordinates.{" "}
            <code className="rounded bg-muted px-1 font-mono text-[12px]">validate-figure</code>{" "}
            checks structure; layout is yours (or the agent's) to invent.
          </>
        }
        actions={
          <Button
            size="sm"
            onClick={handleValidate}
            disabled={validation.status === "checking"}
          >
            <Play className="size-3.5" />
            {validation.status === "checking" ? "Validating…" : "Validate"}
          </Button>
        }
      />

      <Section
        title="Examples"
        description="Click to load. Tweak any field and watch the SVG update; click Validate to feel the structural check the agent will get."
      >
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.name}
              onClick={() => {
                setSource(JSON.stringify(ex.spec, null, 2));
                setValidation({ status: "idle" });
              }}
              className="group inline-flex items-center gap-1.5 rounded-md border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground"
            >
              <Wand2 className="size-3 text-muted-foreground/70 group-hover:text-primary" />
              {ex.name}
            </button>
          ))}
        </div>
      </Section>

      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Source">
          <textarea
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setValidation({ status: "idle" });
            }}
            spellCheck={false}
            className="min-h-[460px] w-full resize-y rounded-md border bg-card px-3 py-2 font-mono text-[13px] leading-relaxed shadow-sm focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
          <ValidationBadge state={validation} parsed={parsed} />
        </Section>

        <Section title="Render">
          <Card>
            <CardContent className="min-h-[460px] p-4">
              {parsed.ok ? (
                <Figure spec={parsed.value} />
              ) : (
                <div className="flex h-[420px] items-center justify-center text-xs text-muted-foreground">
                  fix the JSON parse error to see a render
                </div>
              )}
            </CardContent>
          </Card>
        </Section>
      </div>
    </PageContainer>
  );
}

function ValidationBadge({
  state,
  parsed,
}: {
  state: ValidationState;
  parsed: { ok: true; value: FigureSpec } | { ok: false; error: string };
}) {
  if (!parsed.ok) {
    return (
      <Badge
        variant="outline"
        className="gap-1.5 border-destructive/40 bg-destructive/10 text-destructive"
      >
        <XCircle className="size-3.5" />
        invalid JSON: {parsed.error}
      </Badge>
    );
  }
  if (state.status === "idle") {
    return (
      <p className="text-xs text-muted-foreground">
        Hit <span className="font-semibold">Validate</span> for the
        structural check.
      </p>
    );
  }
  if (state.status === "checking") {
    return <p className="text-xs text-muted-foreground">Calling /api/tools/validate-figure…</p>;
  }
  if (state.status === "valid") {
    return (
      <Badge
        variant="outline"
        className="gap-1.5 border-[var(--success)]/40 bg-[var(--success)]/10 text-[var(--success)]"
      >
        <CheckCircle2 className="size-3.5" />
        valid — agent could submit this
      </Badge>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Badge
        variant="outline"
        className="gap-1.5 border-destructive/40 bg-destructive/10 text-destructive"
      >
        <XCircle className="size-3.5" />
        invalid
        {state.path && (
          <span className="text-[10px] opacity-80">at {state.path}</span>
        )}
      </Badge>
      {state.error && (
        <pre className="whitespace-pre-wrap rounded-md bg-destructive/5 p-2 font-mono text-[11px] text-destructive">
          {state.error}
        </pre>
      )}
    </div>
  );
}
