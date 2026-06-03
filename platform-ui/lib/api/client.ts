import createClient from "openapi-fetch";
import type { paths } from "@/lib/api/schema";

/**
 * Typed client for the platform API. Use from server-side code only
 * (route handlers, server components) — set `PLATFORM_API_URL` in env.
 *
 * Browser code goes through the `/api/...` BFF proxy; we don't expose
 * the upstream origin to the client. Same posture as math-ui.
 */
export function createApiClient(baseUrl?: string) {
  const url = baseUrl ?? process.env.PLATFORM_API_URL;
  if (!url) throw new Error("PLATFORM_API_URL is not configured");
  return createClient<paths>({ baseUrl: url.replace(/\/$/, "") });
}

export type ApiClient = ReturnType<typeof createApiClient>;
