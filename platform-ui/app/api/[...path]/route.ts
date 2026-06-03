/**
 * BFF proxy — forwards every `/api/*` request from the browser to the
 * upstream platform API. Keeps the upstream origin invisible to the
 * client and means CORS doesn't need to be open.
 */
import { NextRequest } from "next/server";

const UPSTREAM = process.env.PLATFORM_API_URL;

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  if (!UPSTREAM) {
    return new Response("PLATFORM_API_URL not configured", { status: 500 });
  }
  const { path } = await params;
  const upstreamUrl = new URL(path.join("/"), UPSTREAM.replace(/\/$/, "") + "/");
  upstreamUrl.search = req.nextUrl.search;

  const headers = new Headers(req.headers);
  headers.delete("host");

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: "manual",
  };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = await req.arrayBuffer();
  }

  const upstreamResp = await fetch(upstreamUrl.toString(), init);
  const responseHeaders = new Headers(upstreamResp.headers);
  // Strip hop-by-hop headers Next would otherwise propagate.
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("transfer-encoding");

  return new Response(upstreamResp.body, {
    status: upstreamResp.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
