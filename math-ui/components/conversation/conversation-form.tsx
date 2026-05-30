"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { conversationClient } from "@/lib/domains/math-conversation";

const MIN_TURNS = 1;
const MAX_TURNS = 30;
const DEFAULT_TURNS = 12;

interface ConversationFormProps {
  onJobStarted: (jobId: string) => void;
}

export function ConversationForm({ onJobStarted }: ConversationFormProps) {
  const [questionText, setQuestionText] = useState("");
  const [maxTurns, setMaxTurns] = useState<number>(DEFAULT_TURNS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!questionText.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await conversationClient.submitFromQuestion(questionText.trim(), maxTurns);
      onJobStarted(res.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit");
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardContent className="pt-5">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              className="text-sm font-medium text-card-foreground"
              htmlFor="conversation-question"
            >
              Math question for the panel
            </label>
            <textarea
              id="conversation-question"
              className="min-h-[110px] w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-card-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 resize-y"
              placeholder="e.g. Explain why the determinant of a 2×2 matrix gives a signed area."
              value={questionText}
              onChange={(e) => setQuestionText(e.target.value)}
              disabled={submitting}
              required
            />
            <p className="text-xs text-muted-foreground">
              A panel of three personae (Algebraist · Visualist · Synthesist) will
              brainstorm the question turn by turn until one calls{" "}
              <code className="font-mono text-[11px]">conclude</code> or the
              turn budget is reached.
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              className="text-sm font-medium text-card-foreground"
              htmlFor="conversation-max-turns"
            >
              Max turns{" "}
              <span className="text-muted-foreground font-normal">
                ({MIN_TURNS}–{MAX_TURNS})
              </span>
            </label>
            <input
              id="conversation-max-turns"
              type="number"
              min={MIN_TURNS}
              max={MAX_TURNS}
              value={maxTurns}
              onChange={(e) =>
                setMaxTurns(
                  Math.min(MAX_TURNS, Math.max(MIN_TURNS, Number(e.target.value) || DEFAULT_TURNS)),
                )
              }
              disabled={submitting}
              className="w-24 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}

          <Button
            type="submit"
            disabled={submitting || !questionText.trim()}
            className="self-start"
          >
            {submitting ? "Submitting…" : "Start conversation"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
