/**
 * Platform-level artifact types — derived from the OpenAPI schema.
 *
 * `Artifact` is the discriminated union over every artifact variant
 * any registered domain produces (driven by the platform router's
 * dynamic union response model). Narrow on `artifact_type` to access
 * domain-specific fields.
 */
import type { components, operations } from "@/lib/api/schema";

type S = components["schemas"];

export type ArtifactSummary = S["ArtifactSummary"];
export type ArtifactListResponse = S["ArtifactListResponse"];

// Registry view: per-type schema as advertised by the backend.
export type ArtifactTypeSpec = S["ArtifactTypeSpec"];
export type ArtifactTypeListResponse = S["ArtifactTypeListResponse"];

export type Artifact = NonNullable<
  operations["get_artifact_artifacts__artifact_id__get"]["responses"][200]["content"]["application/json"]
>;

export type ArtifactType = Artifact["artifact_type"];
