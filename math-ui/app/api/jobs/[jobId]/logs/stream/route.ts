/**
 * SSE proxy for `GET /jobs/{job_id}/logs/stream` upstream.
 *
 * Streams the upstream response body straight through to the browser
 * `EventSource`. Marks the route dynamic and disables Next.js
 * compression for this route so events flush immediately.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MATH_API_URL = process.env.MATH_API_URL;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  if (!MATH_API_URL) {
    return NextResponse.json(
      { error: "MATH_API_URL is not configured" },
      { status: 503 }
    );
  }

  const { jobId } = await params;
  const upstream = await fetch(
    `${MATH_API_URL.replace(/\/$/, "")}/jobs/${encodeURIComponent(jobId)}/logs/stream`,
    {
      headers: { Accept: "text/event-stream" },
      signal: request.signal,
    }
  );

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { error: `upstream ${upstream.status}` },
      { status: 502 }
    );
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
