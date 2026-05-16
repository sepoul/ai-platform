import { proxyGet } from "@/lib/platform/bff-proxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ artifactId: string }> }
) {
  const { artifactId } = await params;
  return proxyGet(`/artifacts/${encodeURIComponent(artifactId)}`);
}
