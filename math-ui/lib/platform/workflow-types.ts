/**
 * Workflow types — server-defined shapes derived from the generated
 * OpenAPI schema, plus a few UI-only types for resolved runtime state.
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

// Job type identifiers come from the backend registry (`GET /workflows`).
// Kept as `string` rather than a literal union — the backend is the
// single source of truth, not a frontend constant.
export type WorkflowJobType = string;

export type ParamSpec = S["ParamSpec"];
export type StageResponse = S["StageResponse"];
export type EdgeResponse = S["EdgeResponse"];
export type GateSpec = S["GateSpec"];
export type WorkflowSpecResponse = S["WorkflowSpecResponse"];
export type WorkflowListItem = S["WorkflowListItem"];
export type WorkflowListResponse = S["WorkflowListResponse"];

export type WorkflowStepRuntimeState =
  | "pending"
  | "active"
  | "complete"
  | "human_wait"
  | "error";

export interface ResolvedWorkflowStep {
  stage: StageResponse;
  state: WorkflowStepRuntimeState;
  orderIndex: number;
}
