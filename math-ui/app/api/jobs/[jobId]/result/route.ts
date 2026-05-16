import { proxyGet } from "@/lib/platform/bff-proxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  return proxyGet(`/jobs/${encodeURIComponent(jobId)}/result`);
}
