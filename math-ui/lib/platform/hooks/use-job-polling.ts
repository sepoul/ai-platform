"use client";

import { useEffect, useState, useCallback } from "react";
import { jobsClient } from "@/lib/platform/jobs-client";
import type { JobStatus } from "@/lib/platform/job-types";
import { TERMINAL_JOB_STATUSES } from "@/lib/platform/job-types";

interface JobPollingState {
  status: JobStatus | null;
  stage: string | null;
  progressMessage: string;
  waitingFor: string | null;
  result: unknown | null;
  error: string | null;
  isLoading: boolean;
}

export function useJobPolling(
  jobId: string | null,
  options?: { interval?: number }
) {
  const intervalMs = options?.interval ?? 2000;
  const [state, setState] = useState<JobPollingState>({
    status: null,
    stage: null,
    progressMessage: "",
    waitingFor: null,
    result: null,
    error: null,
    isLoading: !!jobId,
  });

  const poll = useCallback(async () => {
    if (!jobId) return;
    try {
      const response = await jobsClient.getStatus(jobId);
      setState({
        status: response.status,
        stage: response.stage,
        progressMessage: response.message ?? "",
        waitingFor: response.waiting_for,
        result: response.result,
        error: response.error_message,
        isLoading: !TERMINAL_JOB_STATUSES.includes(response.status),
      });
      return response.status;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to fetch job status";
      setState((prev) => ({
        ...prev,
        status: "FAILED",
        progressMessage: message,
        error: message,
        isLoading: false,
      }));
      return "FAILED" as JobStatus;
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId) {
      setState({
        status: null,
        stage: null,
        progressMessage: "",
        waitingFor: null,
        result: null,
        error: null,
        isLoading: false,
      });
      return;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    const run = async () => {
      const status = await poll();
      if (cancelled || !jobId) return;
      if (status && TERMINAL_JOB_STATUSES.includes(status as JobStatus)) return;
      timeoutId = setTimeout(run, intervalMs);
    };

    run();
    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [jobId, intervalMs, poll]);

  return { ...state, refetch: poll };
}
