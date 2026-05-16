import type {
  Artifact,
  ArtifactListResponse,
  ArtifactTypeListResponse,
} from "./artifacts-types";

async function handleJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let msg: string;
    try {
      const body = (await response.json()) as { error?: string; detail?: string };
      msg = body.error || body.detail || `HTTP ${response.status}`;
    } catch {
      msg = `HTTP ${response.status}`;
    }
    throw new Error(msg);
  }
  return response.json() as Promise<T>;
}

export interface ListArtifactsParams {
  jobId?: string;
  artifactType?: string;
  limit?: number;
}

export async function fetchArtifacts(
  params: ListArtifactsParams = {}
): Promise<ArtifactListResponse> {
  const qs = new URLSearchParams();
  if (params.jobId) qs.set("job_id", params.jobId);
  if (params.artifactType) qs.set("artifact_type", params.artifactType);
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString();
  const url = `/api/artifacts${suffix ? `?${suffix}` : ""}`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  return handleJson<ArtifactListResponse>(res);
}

/**
 * Lists every artifact type the platform knows about — the registry
 * view drives `/artifact-types`.
 */
export async function fetchArtifactTypes(): Promise<ArtifactTypeListResponse> {
  const res = await fetch("/api/artifacts/types", {
    headers: { Accept: "application/json" },
  });
  return handleJson<ArtifactTypeListResponse>(res);
}

export async function fetchArtifact(id: string): Promise<Artifact> {
  const res = await fetch(`/api/artifacts/${encodeURIComponent(id)}`, {
    headers: { Accept: "application/json" },
  });
  return handleJson<Artifact>(res);
}
