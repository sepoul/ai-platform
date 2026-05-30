"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { registerActiveJob } from "@/lib/platform";
import { conversationClient } from "@/lib/domains/math-conversation";

interface StartFromAnswerButtonProps {
  /** The completed math_qa job whose artifacts seed the conversation. */
  sourceJobId: string;
  /** Optional override for the panel's turn budget. */
  maxTurns?: number;
  /** Optional label override; defaults to "Run conversation on this answer". */
  label?: string;
}

/**
 * CTA for completed math_qa job pages: submits a `math_conversation`
 * job seeded from `sourceJobId` (SeedStep hydrates the math_qa
 * artifacts into the panel's context) and redirects to the new
 * conversation view.
 *
 * On submit failure: shows the error inline and stays on the math_qa
 * page so the user doesn't lose context.
 */
export function StartFromAnswerButton({
  sourceJobId,
  maxTurns,
  label = "Run conversation on this answer",
}: StartFromAnswerButtonProps) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await conversationClient.submitFromSourceJob(sourceJobId, maxTurns);
      registerActiveJob({
        jobId: res.job_id,
        jobType: "math_conversation",
        entityId: res.job_id,
        status: "running",
      });
      router.push(`/math-conversation/${res.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start conversation");
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <Button onClick={handleClick} disabled={submitting} variant="outline">
        {submitting ? "Starting…" : label}
      </Button>
      {error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
