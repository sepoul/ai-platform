/**
 * Next.js route-handler factory: forward every browser-side request
 * at `/api/*` to the upstream platform API. Used by both math-ui and
 * platform-ui (and any friend's domain UI) so the upstream URL never
 * leaves the server.
 *
 * Usage in a Next.js app:
 *
 *     // app/api/[...path]/route.ts
 *     import { createBffHandler } from "@aiplatform/sdk/bff";
 *
 *     const handler = createBffHandler({
 *       upstreamUrl: process.env.PLATFORM_API_URL!,
 *     });
 *     export const GET = handler;
 *     export const POST = handler;
 *     export const PUT = handler;
 *     export const DELETE = handler;
 *     export const PATCH = handler;
 *
 * Or as a single-line spread:
 *
 *     export const { GET, POST, PUT, DELETE, PATCH } =
 *       createBffMethods({ upstreamUrl: process.env.PLATFORM_API_URL! });
 */
import type { NextRequest } from "next/server";

export interface BffHandlerOptions {
  /**
   * The upstream platform API base URL (e.g. `http://api:8000`).
   *
   * Accepts a string OR a `() => string` thunk. Prefer the thunk
   * when reading from `process.env` — Next.js's build-time page-
   * data collection imports route modules with envs unset, and a
   * string read at module load (`createBffMethods({upstreamUrl:
   * process.env.X!})`) would crash the build. The thunk resolves
   * per-request instead.
   */
  upstreamUrl: string | (() => string);
  /**
   * Headers always set on the upstream request. Useful for auth tokens
   * minted server-side. Browser-supplied headers (Authorization,
   * cookies, etc.) are forwarded by default; this is an overlay.
   */
  extraHeaders?: Record<string, string>;
}

type RouteHandler = (
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) => Promise<Response>;

/** A single route handler that proxies all HTTP methods. */
export function createBffHandler(opts: BffHandlerOptions): RouteHandler {
  const resolveUpstream = (): string => {
    const raw = typeof opts.upstreamUrl === "function" ? opts.upstreamUrl() : opts.upstreamUrl;
    return raw.replace(/\/$/, "") + "/";
  };
  return async function proxy(req, { params }) {
    const upstream = resolveUpstream();
    const { path } = await params;
    const upstreamUrl = new URL(path.join("/"), upstream);
    upstreamUrl.search = req.nextUrl.search;

    const headers = new Headers(req.headers);
    headers.delete("host");
    if (opts.extraHeaders) {
      for (const [k, v] of Object.entries(opts.extraHeaders)) {
        headers.set(k, v);
      }
    }

    const init: RequestInit = { method: req.method, headers, redirect: "manual" };
    if (!["GET", "HEAD"].includes(req.method)) {
      init.body = await req.arrayBuffer();
    }

    const upstreamResp = await fetch(upstreamUrl.toString(), init);
    const responseHeaders = new Headers(upstreamResp.headers);
    // Hop-by-hop headers Next.js would otherwise propagate.
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("transfer-encoding");

    return new Response(upstreamResp.body, {
      status: upstreamResp.status,
      headers: responseHeaders,
    });
  };
}

/**
 * Convenience: returns an object containing all method handlers so the
 * route file can `export const { GET, POST, … } = createBffMethods(...)`.
 */
export function createBffMethods(opts: BffHandlerOptions) {
  const handler = createBffHandler(opts);
  return {
    GET: handler,
    POST: handler,
    PUT: handler,
    DELETE: handler,
    PATCH: handler,
  };
}
