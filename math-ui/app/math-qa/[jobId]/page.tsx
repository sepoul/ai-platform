"use client";

import { use, useEffect, useState, useCallback } from "react";
import { useJobPolling } from "@/lib/platform";
import { jobsClient } from "@/lib/platform";
import { WorkflowJobRunner } from "@/components/workflow/workflow-job-runner";
import { ReviewForm } from "@/components/math/review-form";
import { ResultDisplay } from "@/components/math/result-display";
import { JobLogs } from "@/components/jobs/job-logs";
import { updateActiveJob, clearActiveJob } from "@/lib/platform";
import type { MathQAResult } from "@/lib/domains/math-qa";
import { PageContainer, PageHeader } from "@/components/library";
import { StartFromAnswerButton } from "@/components/conversation/start-from-answer-button";

interface Props {
  params: Promise<{ jobId: string }>;
}

export default function MathQAJobPage({ params }: Props) {
  const { jobId } = use(params);
  const { status, stage, progressMessage, waitingFor, error } = useJobPolling(jobId);

  const [qaResult, setQaResult] = useState<MathQAResult | null>(null);
  const [loadingResult, setLoadingResult] = useState(false);

  const isWaiting = status === "WAITING_INPUT";
  const isSucceeded = status === "SUCCEEDED";
  const isFailed = status === "FAILED" || status === "CANCELLED";

  // Fetch AI answer when paused for review, or full result when done
  useEffect(() => {
    if (!isWaiting && !isSucceeded) return;
    setLoadingResult(true);
    jobsClient.getResult(jobId)
      // The platform returns the schema-loose result; this page is the
      // math_qa boundary so we narrow to the domain's tightened shape.
      .then((res) => setQaResult(res.result as MathQAResult | null))
      .catch(() => {})
      .finally(() => setLoadingResult(false));
  }, [jobId, isWaiting, isSucceeded]);

  // Sync global job-rail
  useEffect(() => {
    if (isWaiting) updateActiveJob("math_qa", jobId, { status: "waiting_input" });
    if (isSucceeded || isFailed) clearActiveJob("math_qa", jobId);
  }, [jobId, isWaiting, isSucceeded, isFailed]);

  // After review submitted: clear local state so review form hides while polling resumes
  const handleReviewSubmitted = useCallback(() => {
    setQaResult(null);
    updateActiveJob("math_qa", jobId, { status: "running" });
  }, [jobId]);

  return (
    <PageContainer>
      <PageHeader
        title="Math Q&A"
        subtitle={<span className="font-mono text-xs">{jobId}</span>}
      />

      <div className="flex max-w-2xl flex-col gap-6">
        {/* Workflow stepper — always visible until we show the final result */}
        {!isSucceeded && (
          <WorkflowJobRunner
            workflowJobType="math_qa"
            kind="math_qa"
            inProgressTitle="Solving your question…"
            failedTitle="Something went wrong"
            status={status}
            stage={stage}
            message={progressMessage}
            error={error}
            waitingFor={waitingFor}
          />
        )}

        {/* Live worker logs — stops streaming once the job is terminal. */}
        <JobLogs jobId={jobId} enabled={!isSucceeded && !isFailed} />

        {/* Human review — shown only while paused and result is loaded */}
        {isWaiting && !loadingResult && qaResult && (
          <ReviewForm
            jobId={jobId}
            question={qaResult.question}
            aiResponse={qaResult.ai_response}
            latex={qaResult.latex}
            onReviewSubmitted={handleReviewSubmitted}
          />
        )}

        {/* Final result */}
        {isSucceeded && (
          <>
            <WorkflowJobRunner
              workflowJobType="math_qa"
              kind="math_qa"
              inProgressTitle=""
              failedTitle=""
              status={status}
              stage={stage}
              message={progressMessage}
              error={error}
              waitingFor={waitingFor}
            />
            {loadingResult && (
              <p className="text-sm text-muted-foreground">Loading result…</p>
            )}
            {!loadingResult && qaResult && (
              <>
                <ResultDisplay result={qaResult} />
                {/* CTA: spin up a math_conversation panel seeded from this
                 * job's artifacts. SeedStep hydrates the question/answer/
                 * latex/figure into the panel's context. */}
                <StartFromAnswerButton sourceJobId={jobId} />
              </>
            )}
          </>
        )}
      </div>
    </PageContainer>
  );
}
