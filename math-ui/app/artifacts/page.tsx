"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchArtifacts, type ArtifactSummary } from "@/lib/platform";
import {
  EmptyCard,
  ErrorCard,
  LinkCard,
  LoadingCard,
  PageContainer,
  PageHeader,
} from "@/components/library";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

const ALL = "__all__";

export default function ArtifactsIndexPage() {
  const [items, setItems] = useState<ArtifactSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchArtifacts({ limit: 200 })
      .then((res) => {
        if (!cancelled) setItems(res.artifacts);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = useMemo(() => groupByType(items ?? []), [items]);
  const types = useMemo(() => Object.keys(grouped).sort(), [grouped]);

  return (
    <PageContainer>
      <PageHeader
        title="Artifacts"
        subtitle="Hydrated workspace artifacts across every registered domain. Each row links to the typed detail view."
      />

      {error && <ErrorCard>{error}</ErrorCard>}
      {!items && !error && <LoadingCard rows={6} />}
      {items && items.length === 0 && (
        <EmptyCard>No artifacts in the workspace.</EmptyCard>
      )}

      {items && items.length > 0 && (
        <Tabs defaultValue={ALL} className="gap-4">
          <TabsList className="h-auto flex-wrap justify-start gap-1 bg-transparent p-0">
            <TabTriggerWithCount value={ALL} label="All" count={items.length} />
            {types.map((t) => (
              <TabTriggerWithCount
                key={t}
                value={t}
                label={t}
                count={grouped[t].length}
                mono
              />
            ))}
          </TabsList>

          <TabsContent value={ALL} className="mt-0">
            <ArtifactRows rows={items} />
          </TabsContent>
          {types.map((t) => (
            <TabsContent key={t} value={t} className="mt-0">
              <ArtifactRows rows={grouped[t]} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </PageContainer>
  );
}

function TabTriggerWithCount({
  value,
  label,
  count,
  mono,
}: {
  value: string;
  label: string;
  count: number;
  mono?: boolean;
}) {
  return (
    <TabsTrigger
      value={value}
      className="data-[state=active]:bg-secondary data-[state=active]:shadow-sm gap-1.5 rounded-md border border-transparent px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground data-[state=active]:border-border data-[state=active]:text-foreground"
    >
      <span className={mono ? "font-mono" : ""}>{label}</span>
      <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground">
        {count}
      </span>
    </TabsTrigger>
  );
}

function ArtifactRows({ rows }: { rows: ArtifactSummary[] }) {
  if (rows.length === 0) {
    return <EmptyCard>No artifacts of this type.</EmptyCard>;
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row) => (
        <LinkCard
          key={row.artifact_id}
          href={`/artifacts/${encodeURIComponent(row.artifact_id)}`}
          contentClassName="px-4 py-3"
        >
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="secondary" className="font-mono text-[11px]">
              {row.artifact_type}
            </Badge>
            <span className="font-mono text-xs">{row.artifact_id}</span>
            <span className="text-xs text-muted-foreground">
              {new Date(row.created_at).toLocaleString()}
            </span>
            {row.created_by_job && (
              <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                job: {row.created_by_job}
              </span>
            )}
          </div>
        </LinkCard>
      ))}
    </div>
  );
}

function groupByType(rows: ArtifactSummary[]): Record<string, ArtifactSummary[]> {
  const out: Record<string, ArtifactSummary[]> = {};
  for (const row of rows) {
    (out[row.artifact_type] ??= []).push(row);
  }
  return out;
}
