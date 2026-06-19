/**
 * BFF proxy — forwards every `/api/*` request to the upstream
 * platform API. Implementation lives in `@sepoul-packages/sdk` so
 * math-ui and any friend's domain UI use the exact same code path.
 *
 * The upstream URL is resolved per-request from `PLATFORM_API_URL`
 * (via the SDK's thunk form). Reading the env at module load would
 * crash Next.js's build-time page-data collection step, which
 * imports route modules with env unset.
 */
import { createBffMethods } from "@sepoul-packages/sdk";

export const { GET, POST, PUT, DELETE, PATCH } = createBffMethods({
  upstreamUrl: () => {
    const url = process.env.PLATFORM_API_URL;
    if (!url) throw new Error("PLATFORM_API_URL is not configured");
    return url;
  },
});
