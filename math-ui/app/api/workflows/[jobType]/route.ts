import { proxyGet } from "@/lib/platform/bff-proxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobType: string }> }
) {
  const { jobType } = await params;
  return proxyGet(`/workflows/${encodeURIComponent(jobType)}`);
}
