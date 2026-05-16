import { NextResponse } from "next/server";

const MATH_API_URL = process.env.MATH_API_URL;

function getBaseUrl(): string {
  if (!MATH_API_URL) throw new Error("MATH_API_URL is not configured");
  return MATH_API_URL.replace(/\/$/, "");
}

async function fetchUpstream(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${getBaseUrl()}${path}`, init ?? {});
}

export async function proxyGet(path: string): Promise<NextResponse> {
  try {
    const upstream = await fetchUpstream(path);
    const body = await upstream.json();
    return NextResponse.json(body, { status: upstream.status });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Math API unavailable";
    return NextResponse.json({ error: msg }, { status: 503 });
  }
}

export async function proxyPostJson(path: string, payload: unknown): Promise<NextResponse> {
  try {
    const upstream = await fetchUpstream(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await upstream.json();
    return NextResponse.json(body, { status: upstream.status });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Math API unavailable";
    return NextResponse.json({ error: msg }, { status: 503 });
  }
}
