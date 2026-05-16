"use client";

import { useMemo, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronUp } from "lucide-react";
import { RichJobProgress } from "@/components/job-progress/rich-job-progress";
import { WorkflowStepperView } from "@/components/workflow/workflow-stepper-view";
import { WorkflowGraphView } from "@/components/workflow/workflow-graph-view";
import { useWorkflowSpec } from "@/lib/platform";
import { resolveWorkflowStepStates } from "@/lib/platform";
import type { WorkflowJobType, WorkflowSpecResponse } from "@/lib/platform";
import type { JobProgressKind } from "@/lib/domains/math-qa";

export interface WorkflowJobRunnerProps {
  workflowJobType?: WorkflowJobType | null;
  workflowSpec?: WorkflowSpecResponse | null;
  kind: JobProgressKind;
  inProgressTitle: string;
  failedTitle: string;
  status: string | null;
  stage: string | null;
  message: string;
  error: string | null;
  waitingFor?: string | null;
  onRetry?: () => void;
}

/**
 * Generic job runner: fetches workflow definition by job type, renders a live stepper
 * aligned with backend `stage` / `status`, optional process map (graph).
 */
export function WorkflowJobRunner({
  workflowJobType,
  workflowSpec,
  kind,
  inProgressTitle,
  failedTitle,
  status,
  stage,
  message,
  error,
  waitingFor,
  onRetry,
}: WorkflowJobRunnerProps) {
  const specSource =
    workflowSpec != null ? null : (workflowJobType ?? null);
  const { spec, loading, error: specError } = useWorkflowSpec(
    specSource,
    workflowSpec
  );
  const [graphOpen, setGraphOpen] = useState(false);
  const [hoveredStageId, setHoveredStageId] = useState<string | null>(null);

  const { orderedSteps } = useMemo(() => {
    if (!spec) {
      return { orderedSteps: [], currentStageId: null as string | null };
    }
    return resolveWorkflowStepStates(spec, {
      status,
      stage,
      errorMessage: error,
    });
  }, [spec, status, stage, error]);

  const stateByStageId = useMemo(
    () => new Map(orderedSteps.map((s) => [s.stage.id, s.state])),
    [orderedSteps]
  );

  const scrollToStep = useCallback((stageId: string) => {
    const el = document.getElementById(`workflow-step-${stageId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  const stepperBlock =
    spec && !loading ? (
      <WorkflowStepperView
        orderedSteps={orderedSteps}
        onStepHover={setHoveredStageId}
      />
    ) : loading ? (
      <p className="text-xs text-[var(--color-text-muted)]">Loading steps…</p>
    ) : specError ? (
      <p className="text-xs text-[var(--color-text-muted)]">
        Steps couldn&apos;t be loaded ({specError}). The summary below still applies.
      </p>
    ) : null;

  const processOverviewBlock =
    spec && !loading ? (
      <div className="rounded-lg border border-dashed border-border bg-card/60">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setGraphOpen((o) => !o)}
          className="flex w-full items-center justify-between gap-2 rounded-b-none px-3 text-xs font-medium text-muted-foreground"
          aria-expanded={graphOpen}
        >
          <span>Process overview</span>
          {graphOpen ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </Button>
        {graphOpen && (
          <div className="border-t border-border p-2">
            <WorkflowGraphView
              spec={spec}
              stateByStageId={stateByStageId}
              jobStatus={status}
              highlightedStageId={hoveredStageId}
              onNodeSelect={scrollToStep}
            />
          </div>
        )}
      </div>
    ) : null;

  return (
    <RichJobProgress
      kind={kind}
      inProgressTitle={inProgressTitle}
      failedTitle={failedTitle}
      status={status}
      stage={stage}
      message={message}
      error={error}
      waitingFor={waitingFor}
      onRetry={onRetry}
      stepper={stepperBlock}
      processOverview={processOverviewBlock}
    />
  );
}
