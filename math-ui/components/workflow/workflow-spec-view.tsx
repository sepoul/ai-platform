"use client";

import { useMemo } from "react";
import type { WorkflowSpecResponse } from "@/lib/platform";
import { WorkflowGraphView } from "@/components/workflow/workflow-graph-view";
import { Badge } from "@/components/ui/badge";
import {
  FieldBadge,
  FieldList,
  Section,
  type FieldRow,
} from "@/components/library";

/**
 * Static, runtime-state-free view of a workflow spec. Used by the
 * platform-level workflow detail page; no job is bound. For the live
 * runner that overlays job state, see `WorkflowJobRunner`.
 */
export function WorkflowSpecView({ spec }: { spec: WorkflowSpecResponse }) {
  const emptyStates = useMemo(() => new Map<string, never>(), []);

  const submitParamRows: FieldRow[] = spec.submit_params.map((p) => ({
    name: p.name,
    badges: [
      <FieldBadge key="type" mono>
        {p.type}
      </FieldBadge>,
      <FieldBadge key="required" variant={p.required ? "secondary" : "outline"}>
        {p.required ? "required" : "optional"}
      </FieldBadge>,
    ],
    description: p.description || undefined,
  }));

  return (
    <div className="flex flex-col gap-8">
      {submitParamRows.length > 0 && (
        <Section
          title="Submit parameters"
          description="Fields a client provides when starting a new run."
        >
          <FieldList rows={submitParamRows} />
        </Section>
      )}

      <Section
        title="Graph"
        description="Stage topology — pending state until a job is bound."
      >
        <div className="h-[380px] overflow-hidden rounded-lg border bg-card">
          <WorkflowGraphView
            spec={spec}
            stateByStageId={emptyStates}
            jobStatus={null}
          />
        </div>
      </Section>

      {spec.gates.length > 0 && (
        <Section
          title="Execution policy"
          description={`${spec.gates.length} review gate${spec.gates.length === 1 ? "" : "s"} — workflow pauses after each gated node until the review is submitted.`}
        >
          <div className="flex flex-col gap-2">
            {spec.gates.map((gate) => (
              <div
                key={gate.node_name}
                className="flex flex-col gap-1.5 rounded-lg border bg-card px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-sm font-medium">
                    {gate.node_name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    awaits{" "}
                    <span className="font-mono">{gate.review_type}</span>
                  </span>
                </div>
                {gate.params.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {gate.params.map((p) => (
                      <FieldBadge key={p.name} mono>
                        {p.name}: {p.type}
                        {p.required ? "" : "?"}
                      </FieldBadge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section
        title="Stages"
        description={`${spec.stages.length} stage${spec.stages.length === 1 ? "" : "s"}.`}
      >
        <div className="flex flex-col gap-2">
          {spec.stages.map((stage) => (
            <div
              key={stage.id}
              className="flex flex-col gap-1.5 rounded-lg border bg-card px-4 py-3"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-sm font-medium">
                  {stage.id}
                </span>
                <span className="text-xs text-muted-foreground">
                  {stage.label}
                </span>
                {stage.is_human_step && (
                  <Badge
                    variant="outline"
                    className="border-[var(--warning)]/40 bg-[var(--warning)]/10 text-[10.5px] font-medium uppercase tracking-wide text-[var(--warning)]"
                  >
                    human
                  </Badge>
                )}
              </div>
              {stage.description && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {stage.description}
                </p>
              )}
              {stage.resume_params.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {stage.resume_params.map((p) => (
                    <FieldBadge key={p.name} mono>
                      {p.name}: {p.type}
                    </FieldBadge>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
