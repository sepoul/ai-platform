/**
 * `@sepoul-packages/sdk` — TypeScript client for ai-platform.
 *
 * Mirror of the Python `PlatformSession` API. Two main entry points:
 *
 * - `new PlatformSession({ apiUrl })` for catalog reads + job
 *   lifecycle (`submitJob`, `JobHandle.wait`, `.result`).
 * - `createBffHandler` / `createBffMethods` for Next.js route
 *   handlers that proxy the browser to the upstream platform API.
 *   Server-only — imports `next/server`; tree-shaken out of client
 *   bundles by Next's per-route splitting.
 */

export {
  PlatformSession,
  JobHandle,
  PlatformSessionError,
  JobNotFoundError,
  JobTimeoutError,
  type PlatformSessionOptions,
  type ListArtifactsOpts,
} from "./session.js";

export { createApiClient, type ApiClient } from "./client.js";

export {
  createBffHandler,
  createBffMethods,
  type BffHandlerOptions,
} from "./bff.js";

export {
  TERMINAL_STATUSES,
  type JobDefinitionRecord,
  type JobDefinitionRecordInput,
  type ArtifactTypeRecord,
  type CodePackageRecord,
  type JobStatusResponse,
  type JobResultResponse,
  type RunSubmitResponse,
  type UserComment,
  // Artifacts (legacy registry endpoints — coexist with /artifact-types)
  type Artifact,
  type ArtifactType,
  type ArtifactSummary,
  type ArtifactListResponse,
  type FullArtifactListResponse,
  type ArtifactTypeSpec,
  type ArtifactTypeListResponse,
  // Workflows
  type ParamSpec,
  type StageResponse,
  type EdgeResponse,
  type GateSpec,
  type WorkflowSpecResponse,
  type WorkflowListItem,
  type WorkflowListResponse,
} from "./types.js";

// Re-export the raw schema so power users can reach for
// `components["schemas"]["..."]` directly.
export type { components, paths } from "./schema.js";
