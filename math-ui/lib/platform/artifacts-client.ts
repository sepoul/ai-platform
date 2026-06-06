/**
 * Thin wrapper over `@aiplatform/sdk`'s `PlatformSession`.
 */
import { platformSession } from "@/lib/session";
import type {
  Artifact,
  ArtifactListResponse,
  ArtifactTypeListResponse,
} from "./artifacts-types";

export interface ListArtifactsParams {
  jobId?: string;
  artifactType?: string;
  limit?: number;
}

export function fetchArtifacts(
  params: ListArtifactsParams = {}
): Promise<ArtifactListResponse> {
  return platformSession().listArtifacts(params);
}

/**
 * Calls the legacy `/artifacts/types` registry endpoint, not the new
 * `/artifact-types` catalog.
 */
export function fetchArtifactTypes(): Promise<ArtifactTypeListResponse> {
  return platformSession().listArtifactTypesRegistry();
}

export function fetchArtifact(id: string): Promise<Artifact> {
  return platformSession().getArtifact(id) as Promise<Artifact>;
}
