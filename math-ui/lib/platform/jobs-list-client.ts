import type { JobStatusResponse } from "./job-types";

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg: string;
    try {
      const body = (await res.json()) as { error?: string; detail?: string };
      msg = body.error || body.detail || `HTTP ${res.status}`;
    } catch {
      msg = `HTTP ${res.status}`;
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export interface ListJobsParams {
  status?: string;
  jobType?: string;
  createdAfter?: string;     // YYYY-MM-DD
  createdBefore?: string;    // YYYY-MM-DD
  limit?: number;
  offset?: number;
}

/**
 * Lists job records (history) — backed by `GET /jobs` on the platform
 * router. The list is sorted server-side, newest first.
 */
export async function fetchJobs(
  params: ListJobsParams = {}
): Promise<JobStatusResponse[]> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.jobType) qs.set("job_type", params.jobType);
  if (params.createdAfter) qs.set("created_after", params.createdAfter);
  if (params.createdBefore) qs.set("created_before", params.createdBefore);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString();
  const url = `/api/jobs${suffix ? `?${suffix}` : ""}`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  return handleJson<JobStatusResponse[]>(res);
}
