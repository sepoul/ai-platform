/**
 * Workflow types — re-exported from `@aiplatform/sdk`, plus a few
 * UI-only types for resolved runtime state used by workflow-graph.
 */
export type {
  ParamSpec,
  StageResponse,
  EdgeResponse,
  GateSpec,
  WorkflowSpecResponse,
  WorkflowListItem,
  WorkflowListResponse,
} from "@aiplatform/sdk";
import type { StageResponse } from "@aiplatform/sdk";

// Job type identifiers come from the backend registry (`GET /workflows`).
// Kept as `string` rather than a literal union — the backend is the
// single source of truth.
export type WorkflowJobType = string;

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
