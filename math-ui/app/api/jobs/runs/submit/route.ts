import { proxyPostJson } from "@/lib/platform/bff-proxy";

export async function POST(request: Request) {
  const body = await request.json();
  return proxyPostJson("/jobs/runs/submit", body);
}
