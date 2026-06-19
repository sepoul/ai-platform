/**
 * Server-side fetchers for the three platform catalogs. Thin
 * wrappers over `@sepoul-packages/sdk`'s `PlatformSession`. The record
 * types are re-exported here for ergonomic local imports.
 */
import { platformSession } from "@/lib/session";
import type {
  ArtifactTypeRecord,
  CodePackageRecord,
  JobDefinitionRecord,
} from "@sepoul-packages/sdk";

export type { ArtifactTypeRecord, CodePackageRecord, JobDefinitionRecord };

export function listJobDefinitions(): Promise<JobDefinitionRecord[]> {
  return platformSession().listJobDefinitions();
}

export function listArtifactTypes(): Promise<ArtifactTypeRecord[]> {
  return platformSession().listArtifactTypes();
}

export function listCodePackages(): Promise<CodePackageRecord[]> {
  return platformSession().listCodePackages();
}
