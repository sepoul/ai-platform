/**
 * Server-side fetchers for the jobs / runs surface.
 *
 * `GET /jobs[?status=&job_type=&limit=]` returns a list of typed
 * status rows; `GET /jobs/{id}` and `GET /jobs/{id}/result` give
 * the per-job drill-down (status preview is on every list row;
 * the full result is fetched separately because of the 200 vs 409
 * gating on the API).
 */
import { createApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type JobStatusResponse = components["schemas"]["JobStatusResponse"];
export type JobResultResponse = components["schemas"]["JobResultResponse"];

export type ListJobsParams = {
  status?: string;
  job_type?: string;
  limit?: number;
};

export async function listJobs(
  params: ListJobsParams = {},
): Promise<JobStatusResponse[]> {
  const client = createApiClient();
  const { data, error } = await client.GET("/jobs", { params: { query: params } });
  if (error) throw new Error(`/jobs failed: ${JSON.stringify(error)}`);
  return data ?? [];
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const client = createApiClient();
  const { data, error } = await client.GET("/jobs/{job_id}", {
    params: { path: { job_id: jobId } },
  });
  if (error) throw new Error(`/jobs/${jobId} failed: ${JSON.stringify(error)}`);
  if (!data) throw new Error(`/jobs/${jobId} returned empty body`);
  return data;
}

/**
 * Fetch a job's result. Returns `null` if the job isn't in a
 * result-fetchable status (the API returns 409 for
 * non-SUCCEEDED/non-WAITING_INPUT statuses) — the caller renders
 * accordingly without bubbling the error.
 */
export async function getJobResult(
  jobId: string,
): Promise<JobResultResponse | null> {
  const client = createApiClient();
  const { data, error, response } = await client.GET("/jobs/{job_id}/result", {
    params: { path: { job_id: jobId } },
  });
  if (response.status === 409) return null;
  if (error) {
    throw new Error(`/jobs/${jobId}/result failed: ${JSON.stringify(error)}`);
  }
  return data ?? null;
}
