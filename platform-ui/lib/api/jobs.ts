/**
 * Server-side fetchers for the jobs / runs surface. Thin wrappers
 * over `@sepoul-packages/sdk`'s `PlatformSession`.
 */
import { platformSession } from "@/lib/session";
import type { JobResultResponse, JobStatusResponse } from "@sepoul-packages/sdk";

export type { JobResultResponse, JobStatusResponse };

export type ListJobsParams = {
  status?: string;
  job_type?: string;
  limit?: number;
};

export function listJobs(params: ListJobsParams = {}): Promise<JobStatusResponse[]> {
  return platformSession().listJobs({
    status: params.status,
    jobType: params.job_type,
    limit: params.limit,
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return platformSession().fetchJobStatus(jobId);
}

export function getJobResult(jobId: string): Promise<JobResultResponse | null> {
  return platformSession().fetchJobResult(jobId);
}
