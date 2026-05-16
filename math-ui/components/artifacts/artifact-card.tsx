"use client";

import type { Artifact } from "@/lib/platform";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Figure, Latex, Markdown, type FigureSpec } from "@/components/library";

/**
 * Renders a hydrated artifact, narrowed by `artifact_type`. New domain
 * artifacts fall through to a generic JSON dump until a dedicated
 * renderer is added — see the root NEXT_BEST_STEPS.md "Frontend §7b"
 * for the registry idea.
 */
export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-baseline gap-2">
          <Badge variant="secondary" className="font-mono text-[11px]">
            {artifact.artifact_type}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground">
            {artifact.artifact_id}
          </span>
        </div>

        <ArtifactBody artifact={artifact} />

        <Separator />
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          {artifact.created_at && (
            <span>created {new Date(artifact.created_at).toLocaleString()}</span>
          )}
          {artifact.created_by_job && (
            <span>
              job <span className="font-mono">{artifact.created_by_job}</span>
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ArtifactBody({ artifact }: { artifact: Artifact }) {
  switch (artifact.artifact_type) {
    case "math_question":
      return (
        <div className="flex flex-col gap-2">
          <p className="text-sm leading-relaxed">{artifact.question_text}</p>
          {(artifact.topic || artifact.difficulty) && (
            <div className="flex flex-wrap gap-1.5">
              {artifact.topic && (
                <Badge variant="outline" className="text-[11px]">
                  {artifact.topic}
                </Badge>
              )}
              {artifact.difficulty && (
                <Badge variant="outline" className="text-[11px]">
                  {artifact.difficulty}
                </Badge>
              )}
            </div>
          )}
        </div>
      );

    case "ai_answer":
      return (
        <div className="flex flex-col gap-3">
          <Markdown>{artifact.answer_text}</Markdown>
          {artifact.reasoning_steps && artifact.reasoning_steps.length > 0 && (
            <ol className="list-decimal space-y-1.5 pl-5 text-xs leading-relaxed marker:text-muted-foreground">
              {artifact.reasoning_steps.map((step, i) => (
                <li key={i}>
                  <Markdown>{step}</Markdown>
                </li>
              ))}
            </ol>
          )}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span>confidence {Math.round(artifact.confidence * 100)}%</span>
            {artifact.model_used && (
              <Badge variant="outline" className="font-mono text-[11px]">
                {artifact.model_used}
              </Badge>
            )}
          </div>
        </div>
      );

    case "user_comment":
      return (
        <div className="flex flex-col gap-2">
          <p className="text-sm leading-relaxed">{artifact.comment_text}</p>
          <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            {artifact.rating != null && <span>rating {artifact.rating}/5</span>}
            {artifact.is_correct != null && (
              <span>marked {artifact.is_correct ? "correct" : "incorrect"}</span>
            )}
          </div>
        </div>
      );

    case "figure":
      return (
        <div className="flex flex-col gap-3">
          <Figure spec={artifact.spec as unknown as FigureSpec} />
          <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            <span>template: {artifact.template}</span>
            <span>· attempts: {artifact.validation_attempts}</span>
          </div>
          <details className="rounded-md border bg-muted/40 px-3 py-2 text-xs">
            <summary className="cursor-pointer font-mono text-muted-foreground">
              spec
            </summary>
            <pre className="mt-2 overflow-auto whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed">
              {JSON.stringify(artifact.spec, null, 2)}
            </pre>
          </details>
        </div>
      );

    case "latex_answer":
      return (
        <div className="flex flex-col gap-3">
          <Latex>{artifact.latex_source}</Latex>
          <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            <span>
              {artifact.is_valid ? "validated" : "INVALID"} · attempts{" "}
              {artifact.validation_attempts}
            </span>
          </div>
          <details className="rounded-md border bg-muted/40 px-3 py-2 text-xs">
            <summary className="cursor-pointer font-mono text-muted-foreground">
              source
            </summary>
            <pre className="mt-2 overflow-auto whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed">
              {artifact.latex_source}
            </pre>
          </details>
        </div>
      );

    default:
      return (
        <pre className="overflow-auto rounded-md bg-muted p-3 font-mono text-[11.5px] leading-relaxed">
          {JSON.stringify(artifact, null, 2)}
        </pre>
      );
  }
}
