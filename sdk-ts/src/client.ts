/**
 * Thin typed wrapper over `openapi-fetch`. Used internally by
 * `PlatformSession`; also re-exported for callers that want lower-
 * level GET/POST against the platform API.
 */
import createClient from "openapi-fetch";
import type { paths } from "./schema";

export type ApiClient = ReturnType<typeof createClient<paths>>;

export function createApiClient(baseUrl: string): ApiClient {
  return createClient<paths>({ baseUrl: baseUrl.replace(/\/$/, "") });
}
