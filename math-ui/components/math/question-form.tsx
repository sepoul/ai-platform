"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { mathClient } from "@/lib/domains/math-qa";

const TOPICS = [
  "Algebra",
  "Calculus",
  "Geometry",
  "Trigonometry",
  "Statistics",
  "Number Theory",
  "Linear Algebra",
  "Other",
];

interface QuestionFormProps {
  onJobStarted: (jobId: string) => void;
}

export function QuestionForm({ onJobStarted }: QuestionFormProps) {
  const [questionText, setQuestionText] = useState("");
  const [topic, setTopic] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!questionText.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await mathClient.submitQuestion(questionText.trim(), topic || undefined);
      onJobStarted(res.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit question");
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardContent className="pt-5">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-card-foreground" htmlFor="question">
              Math question
            </label>
            <textarea
              id="question"
              className="min-h-[100px] w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-card-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 resize-y"
              placeholder="e.g. Solve x² + 5x + 6 = 0"
              value={questionText}
              onChange={(e) => setQuestionText(e.target.value)}
              disabled={submitting}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-card-foreground" htmlFor="topic">
              Topic <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {TOPICS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTopic(topic === t ? "" : t)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    topic === t
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/50 hover:text-card-foreground"
                  }`}
                  disabled={submitting}
                >
                  {t}
                </button>
              ))}
            </div>
            {topic === "Other" && (
              <Input
                placeholder="Specify topic"
                value={topic === "Other" ? "" : topic}
                onChange={(e) => setTopic(e.target.value)}
                disabled={submitting}
                className="mt-1"
              />
            )}
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}

          <Button type="submit" disabled={submitting || !questionText.trim()} className="self-start">
            {submitting ? "Submitting…" : "Ask AI"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
