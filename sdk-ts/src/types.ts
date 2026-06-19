/**
 * Re-exports of the platform's catalog record types from the generated
 * OpenAPI schema. Consumers `import { JobDefinitionRecord, ... } from
 * "@sepoul-packages/sdk"` and never deal with the `components["schemas"]`
 * indirection or naming gotchas (e.g. `JobDefinitionRecord-Output`).
 */
import type { components, operations } from "./schema";

// FastAPI emits separate input/output variants for models with
// computed/default fields. List endpoints return Output records.
export type JobDefinitionRecord = components["schemas"]["JobDefinitionRecord-Output"];
export type JobDefinitionRecordInput = components["schemas"]["JobDefinitionRecord-Input"];
export type ArtifactTypeRecord = components["schemas"]["ArtifactTypeRecord"];
export type CodePackageRecord = components["schemas"]["CodePackageRecord"];

export type JobStatusResponse = components["schemas"]["JobStatusResponse"];
export type JobResultResponse = components["schemas"]["JobResultResponse"];
export type RunSubmitResponse = components["schemas"]["RunSubmitResponse"];
export type UserComment = components["schemas"]["UserComment"];

// Artifacts — legacy registry surface (`/artifacts*`). Separate from
// the catalog `/artifact-types` introduced in §7p; both endpoints
// coexist while we converge.
export type ArtifactSummary = components["schemas"]["ArtifactSummary"];
export type ArtifactListResponse = components["schemas"]["ArtifactListResponse"];
/** Full-projection page (`GET /artifacts?full=true`): `artifacts` are the
 * full typed `Artifact` union, not summaries. */
export type FullArtifactListResponse = components["schemas"]["FullArtifactListResponse"];
export type ArtifactTypeSpec = components["schemas"]["ArtifactTypeSpec"];
export type ArtifactTypeListResponse = components["schemas"]["ArtifactTypeListResponse"];
/**
 * Discriminated union over every artifact variant any registered
 * domain produces. Derived from the GET response so the union is
 * always in sync with what `/artifacts/{id}` returns at runtime.
 */
export type Artifact = NonNullable<
  operations["get_artifact_artifacts__artifact_id__get"]["responses"][200]["content"]["application/json"]
>;
export type ArtifactType = Artifact["artifact_type"];

// Workflows registry / per-job spec.
export type ParamSpec = components["schemas"]["ParamSpec"];
export type StageResponse = components["schemas"]["StageResponse"];
export type EdgeResponse = components["schemas"]["EdgeResponse"];
// FastAPI namespaces the two GateSpecs (one in JobDefinitionRepository,
// one in workflow_schemas). Workflows want the workflow_schemas variant.
export type GateSpec = components["schemas"]["ai_platform__jobs__workflow_schemas__GateSpec"];
export type WorkflowSpecResponse = components["schemas"]["WorkflowSpecResponse"];
export type WorkflowListItem = components["schemas"]["WorkflowListItem"];
export type WorkflowListResponse = components["schemas"]["WorkflowListResponse"];

/** Terminal statuses for `JobHandle.isDone`. */
export const TERMINAL_STATUSES = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "WAITING_INPUT",
] as const;
