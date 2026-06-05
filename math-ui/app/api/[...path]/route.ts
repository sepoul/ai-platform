/**
 * BFF proxy — forwards every `/api/*` request to the upstream platform
 * API. Implementation lives in `@aiplatform/sdk` so math-ui and
 * platform-ui share the exact same code path.
 *
 * The upstream URL is resolved per-request from `MATH_API_URL` via the
 * SDK's thunk form — reading at module load would crash Next.js's
 * build-time page-data collection step.
 *
 * Exception: `/api/jobs/[jobId]/logs/stream` keeps its dedicated SSE
 * route handler (more specific Next routes win), since it sets
 * dynamic + nodejs runtime + drops compression for immediate flush.
 */
import { createBffMethods } from "@aiplatform/sdk";

export const { GET, POST, PUT, DELETE, PATCH } = createBffMethods({
  upstreamUrl: () => {
    const url = process.env.MATH_API_URL;
    if (!url) throw new Error("MATH_API_URL is not configured");
    return url;
  },
});
