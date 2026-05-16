/**
 * Platform surface — generic job/workflow primitives that any domain
 * can build on. Mirrors the backend's `ai_platform` namespace.
 *
 * Domain code (e.g. math_qa) imports its UI/types/clients from here;
 * domain-specific result + artifact shapes live in
 * `@/lib/domains/<domain>` and are not re-exported.
 */

// Job lifecycle types
export {
  TERMINAL_JOB_STATUSES,
} from "./job-types";
export type {
  JobStatus,
  JobStatusResponse,
  RunSubmitResponse,
  JobResultResponse,
  UserComment,
} from "./job-types";

// Workflow spec types
export type {
  ParamSpec,
  StageResponse,
  EdgeResponse,
  GateSpec,
  WorkflowSpecResponse,
  WorkflowListItem,
  WorkflowListResponse,
  WorkflowJobType,
  WorkflowStepRuntimeState,
  ResolvedWorkflowStep,
} from "./workflow-types";

// Artifact types (discriminated union over every registered domain's variants)
export type {
  Artifact,
  ArtifactType,
  ArtifactSummary,
  ArtifactListResponse,
  ArtifactTypeSpec,
  ArtifactTypeListResponse,
} from "./artifacts-types";

// Clients (browser → Next.js BFF → upstream)
export { jobsClient } from "./jobs-client";
export { fetchWorkflowSpec, fetchWorkflows } from "./workflows-client";
export {
  fetchArtifacts,
  fetchArtifact,
  fetchArtifactTypes,
} from "./artifacts-client";
export { fetchJobs } from "./jobs-list-client";
export type { ListJobsParams } from "./jobs-list-client";
export type { ListArtifactsParams } from "./artifacts-client";

// Workflow rendering primitives
export {
  topologicalStageOrder,
  resolveWorkflowStepStates,
  workflowLayers,
  layoutWorkflowForReactFlow,
} from "./workflow-graph";

// Active-jobs persistence (localStorage-backed)
export {
  registerActiveJob,
  updateActiveJob,
  clearActiveJob,
  clearAllActiveJobs,
  getActiveJob,
  getAllActiveJobs,
} from "./active-jobs-store";
export type {
  ActiveJobType,
  ActiveJobStatus,
  ActiveJobEntry,
} from "./active-jobs-store";

// Hooks
export { useJobPolling } from "./hooks/use-job-polling";
export { useWorkflowSpec } from "./hooks/use-workflow-spec";
export { useActiveJob, useAutoClearOnTerminal } from "./hooks/use-active-job";
export { useJobLogs } from "./hooks/use-job-logs";

// Live worker → UI log types
export type { LogEntry, LogLevel } from "./log-types";
