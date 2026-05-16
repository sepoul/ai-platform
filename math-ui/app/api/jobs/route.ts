import { proxyGet } from "@/lib/platform/bff-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  return proxyGet(`/jobs${qs ? `?${qs}` : ""}`);
}
