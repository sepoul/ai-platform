"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle } from "lucide-react";
import type {
  GeneratedAnswerArtifact,
  LatexAnswerArtifact,
  MathQuestionArtifact,
} from "@/lib/domains/math-qa";
import { jobsClient } from "@/lib/platform";
import { Latex, Markdown } from "@/components/library";

interface ReviewFormProps {
  jobId: string;
  question: MathQuestionArtifact | null;
  aiResponse: GeneratedAnswerArtifact | null;
  latex: LatexAnswerArtifact | null;
  onReviewSubmitted: () => void;
}

export function ReviewForm({
  jobId,
  question,
  aiResponse,
  latex,
  onReviewSubmitted,
}: ReviewFormProps) {
  const [commentText, setCommentText] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [isCorrect, setIsCorrect] = useState<boolean | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!commentText.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await jobsClient.submitReview(jobId, {
        comment_text: commentText.trim(),
        rating,
        is_correct: isCorrect,
      });
      onReviewSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* AI Answer display */}
      {aiResponse && (
        <Card>
          <CardContent className="pt-5 flex flex-col gap-3">
            {question && (
              <div className="rounded-lg bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                <span className="font-medium text-card-foreground">Q: </span>
                {question.question_text}
              </div>
            )}

            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Answer</p>
              <Markdown>{aiResponse.answer_text}</Markdown>
            </div>

            {aiResponse.reasoning_steps.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Step-by-step reasoning
                </p>
                <ol className="flex flex-col gap-2">
                  {aiResponse.reasoning_steps.map((step, i) => (
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

            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-[11px]">
                Confidence: {Math.round(aiResponse.confidence * 100)}%
              </Badge>
              {aiResponse.model_used && (
                <Badge variant="outline" className="text-[11px] font-mono">
                  {aiResponse.model_used}
                </Badge>
              )}
            </div>

            {latex && (
              <div className="border-t pt-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Typeset
                </p>
                <Latex>{latex.latex_source}</Latex>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Review form */}
      <Card>
        <CardContent className="pt-5">
          <p className="mb-4 text-sm font-semibold text-card-foreground">Your review</p>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Correct / Incorrect */}
            <div className="flex flex-col gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">Was the answer correct?</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setIsCorrect(isCorrect === true ? null : true)}
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                    isCorrect === true
                      ? "border-[var(--color-success)] bg-[var(--color-success)]/10 text-[var(--color-success)]"
                      : "border-border text-muted-foreground hover:border-[var(--color-success)]/50"
                  }`}
                  disabled={submitting}
                >
                  <CheckCircle2 className="h-4 w-4" /> Correct
                </button>
                <button
                  type="button"
                  onClick={() => setIsCorrect(isCorrect === false ? null : false)}
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                    isCorrect === false
                      ? "border-destructive bg-destructive/10 text-destructive"
                      : "border-border text-muted-foreground hover:border-destructive/50"
                  }`}
                  disabled={submitting}
                >
                  <XCircle className="h-4 w-4" /> Incorrect
                </button>
              </div>
            </div>

            {/* Star rating */}
            <div className="flex flex-col gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">Rating (optional)</p>
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    onClick={() => setRating(rating === star ? null : star)}
                    className="text-xl transition-transform hover:scale-110"
                    disabled={submitting}
                    aria-label={`${star} star${star > 1 ? "s" : ""}`}
                  >
                    <span style={{ color: rating !== null && star <= rating ? "#f59e0b" : "var(--color-border)" }}>
                      ★
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Comment */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="comment">
                Comment <span className="text-destructive">*</span>
              </label>
              <textarea
                id="comment"
                className="min-h-[80px] w-full rounded-lg border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 resize-y"
                placeholder="Was the reasoning clear? Any corrections?"
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                disabled={submitting}
                required
              />
            </div>

            {error && (
              <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}

            <Button type="submit" disabled={submitting || !commentText.trim()} className="self-start">
              {submitting ? "Submitting…" : "Submit review"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
