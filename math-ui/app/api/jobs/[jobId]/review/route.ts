import { proxyPostJson } from "@/lib/platform/bff-proxy";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const body = await request.json();
  return proxyPostJson(`/jobs/${encodeURIComponent(jobId)}/review`, body);
}
