"use client";

/* eslint-disable react-hooks/set-state-in-effect -- loading/error/fetched state updates belong to fetch effect lifecycle */
import { useEffect, useState } from "react";
import type { WorkflowJobType, WorkflowSpecResponse } from "@/lib/platform/workflow-types";
import { fetchWorkflowSpec } from "@/lib/platform/workflows-client";

export function useWorkflowSpec(
  jobType: WorkflowJobType | null,
  prefetchedSpec?: WorkflowSpecResponse | null
) {
  const [fetched, setFetched] = useState<WorkflowSpecResponse | null>(null);
  const [fetchLoading, setFetchLoading] = useState(
    prefetchedSpec == null && jobType != null
  );
  const [error, setError] = useState<string | null>(null);

  const spec = prefetchedSpec ?? fetched;
  const loading = prefetchedSpec != null ? false : fetchLoading;

  useEffect(() => {
    if (prefetchedSpec != null) {
      return;
    }
    if (!jobType) {
      setFetched(null);
      setError(null);
      setFetchLoading(false);
      return;
    }
    let cancelled = false;
    setFetchLoading(true);
    setError(null);
    fetchWorkflowSpec(jobType)
      .then((s) => {
        if (!cancelled) setFetched(s);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setFetchLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobType, prefetchedSpec]);

  return { spec, loading, error };
}
