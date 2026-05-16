"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Play, Wand2, XCircle } from "lucide-react";
import {
  Latex,
  PageContainer,
  PageHeader,
  Section,
} from "@/components/library";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/**
 * A live LaTeX scratchpad. Type mixed prose + `\(...\)` / `\[...\]`
 * and see KaTeX render it on the right; click **Validate** to round-
 * trip through `/api/tools/validate-latex` (the same endpoint the
 * `validate_latex` agent tool uses) and see the structured pass/fail.
 *
 * The seed examples are the same canonical identities anyone tinkering
 * with KaTeX reaches for — useful as smoke tests and as a starting
 * point.
 */

const SEED = `Euler's identity, the most beautiful equation in mathematics:

\\[ e^{i\\pi} + 1 = 0 \\]

It links \\(e\\), \\(i\\), \\(\\pi\\), \\(0\\), and \\(1\\) — the five
fundamental constants — through addition, multiplication, and
exponentiation.`;

interface Example {
  name: string;
  body: string;
}

const EXAMPLES: Example[] = [
  {
    name: "Euler",
    body: SEED,
  },
  {
    name: "Quadratic",
    body: `For \\(ax^2 + bx + c = 0\\), the roots are

\\[ x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a} \\]`,
  },
  {
    name: "Gauss",
    body: `Gauss's surprise: \\(\\sum_{k=1}^{n} k = \\frac{n(n+1)}{2}\\).

Equivalently, \\[ 1 + 2 + 3 + \\cdots + n = \\binom{n+1}{2}. \\]`,
  },
  {
    name: "Pythagoras",
    body: `In any right triangle: \\[ a^2 + b^2 = c^2. \\]`,
  },
  {
    name: "Riemann ζ",
    body: `The Riemann zeta function: \\[ \\zeta(s) = \\sum_{n=1}^{\\infty} \\frac{1}{n^s} \\quad (\\Re(s) > 1). \\]

Conjecturally, every non-trivial zero satisfies \\(\\Re(s) = \\tfrac{1}{2}\\).`,
  },
  {
    name: "Stokes",
    body: `Stokes's theorem unifies the fundamental theorems of calculus:

\\[ \\int_{\\partial\\Omega} \\omega = \\int_{\\Omega} d\\omega. \\]`,
  },
  {
    name: "Gauss–Bonnet",
    body: `On a closed oriented surface \\(M\\):

\\[ \\int_M K \\, dA + \\oint_{\\partial M} k_g \\, ds = 2\\pi \\chi(M). \\]

Curvature integrated over the surface is a topological invariant — a
small miracle.`,
  },
];

interface ValidationState {
  status: "idle" | "checking" | "valid" | "invalid";
  error?: string;
  segment?: string;
  segmentIndex?: number;
}

export default function LatexPlaygroundPage() {
  const [source, setSource] = useState(SEED);
  const [validation, setValidation] = useState<ValidationState>({
    status: "idle",
  });

  // Live preview is cheap (KaTeX runs synchronously per segment); no
  // debounce needed.
  const preview = useMemo(() => source, [source]);

  const handleValidate = async () => {
    setValidation({ status: "checking" });
    try {
      // `document` mode splits on \(...\) / \[...\] and validates each
      // math segment in isolation — mirrors what the agent's tool does.
      const res = await fetch("/api/tools/validate-latex", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ latex: source, mode: "document" }),
      });
      const body = (await res.json()) as {
        valid: boolean;
        error?: string;
        segment?: string;
        segment_index?: number;
      };
      setValidation(
        body.valid
          ? { status: "valid" }
          : {
              status: "invalid",
              error: body.error ?? "Invalid LaTeX",
              segment: body.segment,
              segmentIndex: body.segment_index,
            }
      );
    } catch (err) {
      setValidation({
        status: "invalid",
        error: err instanceof Error ? err.message : "Validation failed",
      });
    }
  };

  return (
    <PageContainer>
      <PageHeader
        title="LaTeX scratchpad"
        subtitle={
          <>
            Paste prose with <code className="rounded bg-muted px-1 font-mono text-[12px]">{`\\(...\\)`}</code>{" "}
            and{" "}
            <code className="rounded bg-muted px-1 font-mono text-[12px]">{`\\[...\\]`}</code>{" "}
            delimiters. The same KaTeX endpoint the{" "}
            <code className="rounded bg-muted px-1 font-mono text-[12px]">validate_latex</code>{" "}
            agent tool uses powers the validate button.
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
        description="Click to load. They're all KaTeX-valid; tweak them to see how the validator reacts."
      >
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.name}
              onClick={() => {
                setSource(ex.body);
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
            className="min-h-[420px] w-full resize-y rounded-md border bg-card px-3 py-2 font-mono text-[13px] leading-relaxed shadow-sm focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
          <ValidationBadge state={validation} />
        </Section>

        <Section title="Preview">
          <Card>
            <CardContent className="min-h-[420px] p-5">
              <Latex>{preview}</Latex>
            </CardContent>
          </Card>
        </Section>
      </div>
    </PageContainer>
  );
}

function ValidationBadge({ state }: { state: ValidationState }) {
  if (state.status === "idle") {
    return (
      <p className="text-xs text-muted-foreground">
        Hit <span className="font-semibold">Validate</span> to round-trip through KaTeX.
      </p>
    );
  }
  if (state.status === "checking") {
    return <p className="text-xs text-muted-foreground">Calling /api/tools/validate-latex…</p>;
  }
  if (state.status === "valid") {
    return (
      <Badge
        variant="outline"
        className="gap-1.5 border-[var(--success)]/40 bg-[var(--success)]/10 text-[var(--success)]"
      >
        <CheckCircle2 className="size-3.5" />
        valid — KaTeX accepts it
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
        {state.segmentIndex != null && (
          <span className="text-[10px] opacity-80">
            (segment #{state.segmentIndex})
          </span>
        )}
      </Badge>
      {state.segment && (
        <pre className="whitespace-pre-wrap rounded-md border bg-muted/40 p-2 font-mono text-[11px]">
          {state.segment}
        </pre>
      )}
      {state.error && (
        <pre className="whitespace-pre-wrap rounded-md bg-destructive/5 p-2 font-mono text-[11px] text-destructive">
          {state.error}
        </pre>
      )}
    </div>
  );
}
