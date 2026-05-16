"use client";

import { Badge } from "@/components/ui/badge";
import type { ResolvedWorkflowStep } from "@/lib/platform";

function StepGlyph({
  state,
  index,
}: {
  state: ResolvedWorkflowStep["state"];
  index: number;
}) {
  const base =
    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold";

  switch (state) {
    case "complete":
      return (
        <span
          className={`${base} border-[var(--color-success)] bg-[var(--color-success)]/12 text-[var(--color-success)]`}
          aria-label={`Step ${index + 1} complete`}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5 13l4 4L19 7"
            />
          </svg>
        </span>
      );
    case "active":
      return (
        <span
          className={`${base} border-[var(--color-primary)] text-[var(--color-primary)]`}
          aria-label={`Step ${index + 1} in progress`}
        >
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        </span>
      );
    case "human_wait":
      return (
        <span
          className={`${base} border-[var(--color-warning)] bg-[var(--color-warning)]/12 text-[var(--color-warning)]`}
          title="Waiting for your input"
          aria-label={`Step ${index + 1} needs your review`}
        >
          <span aria-hidden>👤</span>
        </span>
      );
    case "error":
      return (
        <span
          className={`${base} border-[var(--color-error)] bg-[var(--color-error)]/10 text-[var(--color-error)]`}
          aria-label={`Step ${index + 1} failed`}
        >
          !
        </span>
      );
    default:
      return (
        <span
          className={`${base} border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-muted)]`}
          aria-label={`Step ${index + 1} pending`}
        >
          {index + 1}
        </span>
      );
  }
}

export interface WorkflowStepperViewProps {
  orderedSteps: ResolvedWorkflowStep[];
  ariaLabel?: string;
  /** Hovering a step highlights the matching node in the process map */
  onStepHover?: (stageId: string | null) => void;
}

/**
 * Business-friendly vertical stepper driven by resolved workflow + live job status.
 */
export function WorkflowStepperView({
  orderedSteps,
  ariaLabel = "Process steps",
  onStepHover,
}: WorkflowStepperViewProps) {
  if (orderedSteps.length === 0) return null;

  return (
    <ol className="space-y-0" aria-label={ariaLabel}>
      {orderedSteps.map((step, i) => {
        const isLast = i === orderedSteps.length - 1;
        return (
          <li
            key={step.stage.id}
            id={`workflow-step-${step.stage.id}`}
            className="flex gap-3 rounded-lg px-0.5 -mx-0.5 transition-colors hover:bg-[var(--color-surface-elevated)]/80"
            onMouseEnter={() => onStepHover?.(step.stage.id)}
            onMouseLeave={() => onStepHover?.(null)}
          >
            <div className="flex flex-col items-center">
              <StepGlyph state={step.state} index={i} />
              {!isLast && (
                <span
                  className="mt-1 w-px flex-1 min-h-[12px] bg-[var(--color-border)]"
                  aria-hidden
                />
              )}
            </div>
            <div className="min-w-0 flex-1 pb-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-[var(--color-text)]">
                  {step.stage.label}
                </span>
                {step.stage.is_human_step && (
                  <Badge
                    variant="outline"
                    className="border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 text-[var(--color-warning)] text-[10px] uppercase tracking-wide"
                  >
                    Your step
                  </Badge>
                )}
              </div>
              {step.stage.description?.trim() && (
                <p className="mt-1 text-xs leading-relaxed text-[var(--color-text-muted)]">
                  {step.stage.description}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
