/**
 * `@aiplatform/sdk` — TypeScript client for ai-platform.
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
} from "./session";

export { createApiClient, type ApiClient } from "./client";

export {
  createBffHandler,
  createBffMethods,
  type BffHandlerOptions,
} from "./bff";

export {
  TERMINAL_STATUSES,
  type JobDefinitionRecord,
  type JobDefinitionRecordInput,
  type ArtifactTypeRecord,
  type CodePackageRecord,
  type JobStatusResponse,
  type JobResultResponse,
} from "./types";

// Re-export the raw schema so power users can reach for
// `components["schemas"]["..."]` directly.
export type { components, paths } from "./schema";
