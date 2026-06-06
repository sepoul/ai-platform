/**
 * Thin wrapper over `@aiplatform/sdk`'s `PlatformSession`.
 *
 * Math-ui's local `JobStatusResponse` tightens optional fields to
 * required nullables; the SDK returns the raw shape. The cast is
 * safe at runtime because the upstream always populates the fields.
 */
import { platformSession } from "@/lib/session";
import type { JobStatusResponse } from "./job-types";

export interface ListJobsParams {
  status?: string;
  jobType?: string;
  createdAfter?: string;     // YYYY-MM-DD
  createdBefore?: string;    // YYYY-MM-DD
  limit?: number;
  offset?: number;
}

export async function fetchJobs(
  params: ListJobsParams = {}
): Promise<JobStatusResponse[]> {
  const rows = await platformSession().listJobs({
    status: params.status,
    jobType: params.jobType,
    limit: params.limit,
    // Note: SDK's listJobs doesn't expose createdAfter/Before/offset
    // yet — the upstream supports them as query params, the SDK just
    // hasn't surfaced them. Add as needed; today no caller passes
    // these.
  });
  return rows as unknown as JobStatusResponse[];
}
