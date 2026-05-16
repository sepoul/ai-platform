import createClient from "openapi-fetch";
import type { paths } from "@/lib/api/schema";

/**
 * Typed client for the upstream Math AI API. Use from server-side code
 * (BFF route handlers, server components) — set `MATH_API_URL` in env.
 *
 * Browser code should keep going through `/api/...` proxy routes; we
 * don't expose the upstream origin to the client.
 */
export function createApiClient(baseUrl?: string) {
  const url = baseUrl ?? process.env.MATH_API_URL;
  if (!url) throw new Error("MATH_API_URL is not configured");
  return createClient<paths>({ baseUrl: url.replace(/\/$/, "") });
}

export type ApiClient = ReturnType<typeof createApiClient>;
