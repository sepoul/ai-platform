import { proxyGet } from "@/lib/platform/bff-proxy";

export async function GET() {
  return proxyGet("/artifacts/types");
}
