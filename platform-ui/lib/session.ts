/**
 * Server-side `PlatformSession` factory. Reads `PLATFORM_API_URL`
 * from the environment once per request; sessions are cheap (just
 * wrap an openapi-fetch client) so this is fine.
 *
 * Browser-side code goes through the BFF proxy at `/api/...`;
 * never imports this file.
 */
import { PlatformSession } from "@aiplatform/sdk";

export function platformSession(): PlatformSession {
  const url = process.env.PLATFORM_API_URL;
  if (!url) throw new Error("PLATFORM_API_URL is not configured");
  return new PlatformSession({ apiUrl: url });
}
