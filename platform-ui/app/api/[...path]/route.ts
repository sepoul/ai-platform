/**
 * BFF proxy — forwards every `/api/*` request to the upstream
 * platform API. Implementation lives in `@aiplatform/sdk/bff` so
 * math-ui and any friend's domain UI use the exact same code path.
 */
import { createBffMethods } from "@aiplatform/sdk";

const UPSTREAM = process.env.PLATFORM_API_URL;
if (!UPSTREAM) {
  // Surface configuration errors at server boot, not at first request.
  throw new Error("PLATFORM_API_URL is not configured");
}

export const { GET, POST, PUT, DELETE, PATCH } = createBffMethods({
  upstreamUrl: UPSTREAM,
});
