"use client";

import { use, useEffect, useState } from "react";
import { fetchArtifact, type Artifact } from "@/lib/platform";
import { ArtifactCard } from "@/components/artifacts/artifact-card";
import {
  ErrorCard,
  LoadingCard,
  PageContainer,
  PageHeader,
} from "@/components/library";

interface Props {
  params: Promise<{ artifactId: string }>;
}

export default function ArtifactDetailPage({ params }: Props) {
  const { artifactId } = use(params);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchArtifact(artifactId)
      .then((a) => {
        if (!cancelled) setArtifact(a);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [artifactId]);

  return (
    <PageContainer>
      <PageHeader
        title="Artifact"
        subtitle={<span className="font-mono text-xs">{artifactId}</span>}
      />

      {error && <ErrorCard>{error}</ErrorCard>}
      {!error && !artifact && <LoadingCard rows={5} />}
      {artifact && <ArtifactCard artifact={artifact} />}
    </PageContainer>
  );
}
