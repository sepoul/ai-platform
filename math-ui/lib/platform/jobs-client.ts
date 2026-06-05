/**
 * Thin wrapper over `@aiplatform/sdk`'s `PlatformSession`. Keeps the
 * existing `jobsClient.submit/getStatus/getResult/submitReview` call
 * sites in math-ui untouched while the underlying client is the SDK.
 */
import type { UserComment } from "@aiplatform/sdk";
import { platformSession } from "@/lib/session";
import type {
  JobStatusResponse,
  JobResultResponse,
  RunSubmitResponse,
} from "./job-types";

interface JobInput {
  job_type: string;
  [field: string]: unknown;
}

export const jobsClient = {
  async submit(input: JobInput): Promise<RunSubmitResponse> {
    const { job_type, ...rest } = input;
    const handle = await platformSession().submitJob(job_type, rest);
    return { job_id: handle.jobId, status: "PENDING" };
  },

  async getStatus(jobId: string): Promise<JobStatusResponse> {
    // The math-ui local type tightens optional fields to required nullable —
    // the SDK returns the raw shape from openapi, the cast is safe.
    return (await platformSession().fetchJobStatus(jobId)) as unknown as JobStatusResponse;
  },

  async getResult(jobId: string): Promise<JobResultResponse> {
    const r = await platformSession().fetchJobResult(jobId);
    if (r === null) {
      // The pre-SDK client treated 409 as a hard error; preserve.
      throw new Error("Job not in a result-fetchable status");
    }
    return r as unknown as JobResultResponse;
  },

  async submitReview(jobId: string, review: UserComment): Promise<RunSubmitResponse> {
    return platformSession().submitReview(jobId, review);
  },
};
