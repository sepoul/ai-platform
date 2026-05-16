import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle, Star } from "lucide-react";
import type { MathQAResult } from "@/lib/domains/math-qa";
import { Figure, Latex, Markdown, type FigureSpec } from "@/components/library";

interface ResultDisplayProps {
  result: MathQAResult;
}

export function ResultDisplay({ result }: ResultDisplayProps) {
  const { question, ai_response, latex, figure, review } = result;

  return (
    <div className="flex flex-col gap-4">
      {/* Question */}
      {question && (
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">Question</p>
            <p className="text-sm text-card-foreground">{question.question_text}</p>
            {question.topic && (
              <Badge variant="outline" className="mt-2 text-[11px]">{question.topic}</Badge>
            )}
          </CardContent>
        </Card>
      )}

      {/* AI Answer */}
      {ai_response && (
        <Card>
          <CardContent className="pt-4 flex flex-col gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">AI Answer</p>
              <Markdown>{ai_response.answer_text}</Markdown>
            </div>

            {ai_response.reasoning_steps.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Reasoning</p>
                <ol className="flex flex-col gap-2">
                  {ai_response.reasoning_steps.map((step, i) => (
                    <li key={i} className="flex gap-2 text-sm text-card-foreground">
                      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1"><Markdown>{step}</Markdown></div>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="text-[11px]">
                Confidence: {Math.round(ai_response.confidence * 100)}%
              </Badge>
              {ai_response.model_used && (
                <Badge variant="outline" className="text-[11px] font-mono">{ai_response.model_used}</Badge>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Figure (when the classifier said yes and the agent converged) */}
      {figure && (
        <Card>
          <CardContent className="pt-4 flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Figure
              </p>
              <span className="text-[11px] text-muted-foreground">
                {figure.template} · validated · {figure.validation_attempts} attempt
                {figure.validation_attempts === 1 ? "" : "s"}
              </span>
            </div>
            <Figure spec={figure.spec as unknown as FigureSpec} />
          </CardContent>
        </Card>
      )}

      {/* Typeset (KaTeX) version of the AI answer */}
      {latex && (
        <Card>
          <CardContent className="pt-4 flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Typeset answer
              </p>
              <span className="text-[11px] text-muted-foreground">
                validated · {latex.validation_attempts} attempt
                {latex.validation_attempts === 1 ? "" : "s"}
              </span>
            </div>
            <Latex>{latex.latex_source}</Latex>
          </CardContent>
        </Card>
      )}

      {/* User feedback */}
      {review && (
        <Card>
          <CardContent className="pt-4 flex flex-col gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Your feedback</p>

            <div className="flex flex-wrap items-center gap-3">
              {review.is_correct !== null && (
                review.is_correct ? (
                  <span className="flex items-center gap-1 text-sm font-medium text-[var(--color-success)]">
                    <CheckCircle2 className="h-4 w-4" /> Marked correct
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-sm font-medium text-destructive">
                    <XCircle className="h-4 w-4" /> Marked incorrect
                  </span>
                )
              )}
              {review.rating !== null && (
                <span className="flex items-center gap-1 text-sm text-muted-foreground">
                  <Star className="h-3.5 w-3.5 fill-[#f59e0b] text-[#f59e0b]" />
                  {review.rating}/5
                </span>
              )}
            </div>

            <p className="text-sm text-card-foreground">{review.comment_text}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
