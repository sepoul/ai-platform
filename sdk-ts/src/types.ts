/**
 * Re-exports of the platform's catalog record types from the generated
 * OpenAPI schema. Consumers `import { JobDefinitionRecord, ... } from
 * "@aiplatform/sdk"` and never deal with the `components["schemas"]`
 * indirection or naming gotchas (e.g. `JobDefinitionRecord-Output`).
 */
import type { components } from "./schema";

// FastAPI emits separate input/output variants for models with
// computed/default fields. List endpoints return Output records.
export type JobDefinitionRecord = components["schemas"]["JobDefinitionRecord-Output"];
export type JobDefinitionRecordInput = components["schemas"]["JobDefinitionRecord-Input"];
export type ArtifactTypeRecord = components["schemas"]["ArtifactTypeRecord"];
export type CodePackageRecord = components["schemas"]["CodePackageRecord"];

export type JobStatusResponse = components["schemas"]["JobStatusResponse"];
export type JobResultResponse = components["schemas"]["JobResultResponse"];

/** Terminal statuses for `JobHandle.isDone`. */
export const TERMINAL_STATUSES = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "WAITING_INPUT",
] as const;
