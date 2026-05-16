"use client";

import { useEffect, useState } from "react";
import {
  fetchArtifactTypes,
  type ArtifactTypeSpec,
} from "@/lib/platform";
import {
  EmptyCard,
  ErrorCard,
  FieldBadge,
  FieldList,
  LoadingCard,
  PageContainer,
  PageHeader,
  type FieldRow,
} from "@/components/library";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Platform artifact-type registry — every `BaseArtifact` subclass any
 * domain has registered, with its field schema. Parallels `/workflows`
 * (workflow-type registry); both surface server-side definitions as
 * first-class UI entities.
 */
export default function ArtifactTypesPage() {
  const [items, setItems] = useState<ArtifactTypeSpec[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchArtifactTypes()
      .then((res) => {
        if (!cancelled) setItems(res.artifact_types);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <PageContainer>
      <PageHeader
        title="Artifact types"
        subtitle="Pydantic classes registered by each domain. The platform serializes these as a discriminated union for typed read access; this page reflects the same schema for humans."
      />

      {error && <ErrorCard>{error}</ErrorCard>}
      {!items && !error && <LoadingCard rows={6} />}
      {items && items.length === 0 && (
        <EmptyCard>No artifact types registered.</EmptyCard>
      )}

      {items && items.length > 0 && (
        <div className="flex flex-col gap-4">
          {items.map((spec) => (
            <ArtifactTypeCard key={spec.artifact_type} spec={spec} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}

function ArtifactTypeCard({ spec }: { spec: ArtifactTypeSpec }) {
  const rows: FieldRow[] = spec.fields.map((f) => ({
    name: f.name,
    badges: [
      <FieldBadge key="type" mono>
        {f.type}
      </FieldBadge>,
      <FieldBadge key="required" variant={f.required ? "secondary" : "outline"}>
        {f.required ? "required" : "optional"}
      </FieldBadge>,
    ],
    description: f.description || undefined,
  }));

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-baseline gap-2">
          <Badge variant="secondary" className="font-mono text-[11px]">
            {spec.artifact_type}
          </Badge>
          <span className="font-mono text-sm font-semibold">
            {spec.class_name}
          </span>
          {spec.domain && (
            <span className="text-xs text-muted-foreground">
              registered by{" "}
              <span className="font-mono">{spec.domain}</span>
            </span>
          )}
        </div>

        {rows.length > 0 ? (
          <FieldList rows={rows} />
        ) : (
          <p className="text-xs text-muted-foreground">
            No fields beyond the discriminator.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
