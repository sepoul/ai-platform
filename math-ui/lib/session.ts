/**
 * Browser-side `PlatformSession` factory. Targets the local Next.js
 * BFF at `/api/...`, which proxies upstream to `MATH_API_URL`. The
 * upstream URL never leaves the server.
 *
 * Server-side code (e.g. a future server component) can call
 * `serverSession()` to skip the BFF and hit the upstream directly.
 */
import { PlatformSession } from "@aiplatform/sdk";

let _browser: PlatformSession | null = null;

/** Shared singleton — fine because PlatformSession just wraps a client. */
export function platformSession(): PlatformSession {
  if (_browser === null) {
    _browser = new PlatformSession({ apiUrl: "/api" });
  }
  return _browser;
}

/** Server-side variant: hits upstream directly. Throws if env unset. */
export function serverSession(): PlatformSession {
  const url = process.env.MATH_API_URL;
  if (!url) throw new Error("MATH_API_URL is not configured");
  return new PlatformSession({ apiUrl: url });
}
