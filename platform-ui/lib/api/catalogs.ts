/**
 * Server-side fetchers for the three platform catalogs. Each one uses
 * the typed `openapi-fetch` client; the returned shape matches the
 * generated `components["schemas"]` types.
 */
import { createApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

// FastAPI emits separate input/output variants for models that have
// computed/default fields. The list endpoints all return Output records.
export type JobDefinitionRecord = components["schemas"]["JobDefinitionRecord-Output"];
export type ArtifactTypeRecord = components["schemas"]["ArtifactTypeRecord"];
export type CodePackageRecord = components["schemas"]["CodePackageRecord"];

export async function listJobDefinitions(): Promise<JobDefinitionRecord[]> {
  const client = createApiClient();
  const { data, error } = await client.GET("/job-definitions", {});
  if (error) throw new Error(`/job-definitions failed: ${JSON.stringify(error)}`);
  return data ?? [];
}

export async function listArtifactTypes(): Promise<ArtifactTypeRecord[]> {
  const client = createApiClient();
  const { data, error } = await client.GET("/artifact-types", {});
  if (error) throw new Error(`/artifact-types failed: ${JSON.stringify(error)}`);
  return data ?? [];
}

export async function listCodePackages(): Promise<CodePackageRecord[]> {
  const client = createApiClient();
  const { data, error } = await client.GET("/code-packages", {});
  if (error) throw new Error(`/code-packages failed: ${JSON.stringify(error)}`);
  return data ?? [];
}
