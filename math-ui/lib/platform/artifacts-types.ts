/**
 * Platform-level artifact types — re-exported from `@aiplatform/sdk`.
 *
 * `Artifact` is the discriminated union over every artifact variant
 * any registered domain produces. Narrow on `artifact_type` to access
 * domain-specific fields.
 */
export type {
  Artifact,
  ArtifactType,
  ArtifactSummary,
  ArtifactListResponse,
  ArtifactTypeSpec,
  ArtifactTypeListResponse,
} from "@aiplatform/sdk";
