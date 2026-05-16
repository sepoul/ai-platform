"use client";

import { useEffect, useRef, useCallback } from "react";
import {
  registerActiveJob,
  clearActiveJob,
  getActiveJob,
  updateActiveJob,
  type ActiveJobType,
  type ActiveJobEntry,
  type ActiveJobStatus,
} from "@/lib/platform/active-jobs-store";

/**
 * Manages localStorage persistence for a single active job.
 *
 * Usage pattern:
 *   const { restore, register, clear } = useActiveJob("diagnostic");
 *
 *   // On mount — check for a previously running job
 *   useEffect(() => {
 *     const prev = restore();
 *     if (prev) { setJobId(prev.jobId); setPhase("processing"); }
 *   }, [restore]);
 *
 *   // When starting a new job
 *   register(jobId);
 *
 *   // When terminal (success/failed/cancelled)
 *   clear();
 */
export function useActiveJob(
  jobType: ActiveJobType,
  entityId?: string
) {
  const jobTypeRef = useRef(jobType);
  const entityIdRef = useRef(entityId);
  jobTypeRef.current = jobType;
  entityIdRef.current = entityId;

  const restore = useCallback((): ActiveJobEntry | null => {
    return getActiveJob(jobTypeRef.current, entityIdRef.current);
  }, []);

  const register = useCallback(
    (jobId: string, meta?: Record<string, string>) => {
      registerActiveJob({
        jobId,
        jobType: jobTypeRef.current,
        entityId: entityIdRef.current,
        meta,
      });
    },
    []
  );

  const clear = useCallback(() => {
    clearActiveJob(jobTypeRef.current, entityIdRef.current);
  }, []);

  const updateStatus = useCallback((status: ActiveJobStatus) => {
    updateActiveJob(jobTypeRef.current, entityIdRef.current, { status });
  }, []);

  return { restore, register, clear, updateStatus };
}

/**
 * Auto-clear helper: watches a status value and calls `clear`
 * when it hits a terminal state. Pairs with useActiveJob.
 */
export function useAutoClearOnTerminal(
  status: string | null,
  clear: () => void,
  terminalStatuses: string[] = ["SUCCEEDED", "FAILED", "CANCELLED", "success", "failed"]
) {
  const clearedRef = useRef(false);

  useEffect(() => {
    if (!status) {
      clearedRef.current = false;
      return;
    }
    if (clearedRef.current) return;
    if (terminalStatuses.includes(status)) {
      clear();
      clearedRef.current = true;
    }
  }, [status, clear, terminalStatuses]);
}
