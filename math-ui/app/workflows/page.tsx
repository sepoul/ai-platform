"use client";

import { useEffect, useState } from "react";
import {
  fetchWorkflows,
  type WorkflowListItem,
} from "@/lib/platform";
import {
  EmptyCard,
  ErrorCard,
  LinkCard,
  LoadingCard,
  PageContainer,
  PageHeader,
} from "@/components/library";

export default function WorkflowsIndexPage() {
  const [items, setItems] = useState<WorkflowListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchWorkflows()
      .then((res) => {
        if (!cancelled) setItems(res.workflows);
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
        title="Workflows"
        subtitle="Domain workflows registered on the platform. Each is defined server-side as a stage graph; the UI renders directly from the OpenAPI spec."
      />

      {error && <ErrorCard>{error}</ErrorCard>}
      {!items && !error && <LoadingCard rows={4} />}
      {items && items.length === 0 && (
        <EmptyCard>No workflows registered.</EmptyCard>
      )}

      {items && items.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <LinkCard
              key={item.job_type}
              href={`/workflows/${encodeURIComponent(item.job_type)}`}
            >
              <p className="font-mono text-sm font-semibold">
                {item.job_type}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {item.label}
              </p>
            </LinkCard>
          ))}
        </div>
      )}
    </PageContainer>
  );
}
