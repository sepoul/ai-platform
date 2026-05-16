import type {
  JobStatusResponse,
  JobResultResponse,
  UserComment,
  RunSubmitResponse,
} from "./job-types";

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

interface JobInput {
  job_type: string;
  [field: string]: unknown;
}

export const jobsClient = {
  async submit(input: JobInput): Promise<RunSubmitResponse> {
    const res = await fetch("/api/jobs/runs/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return handleJson<RunSubmitResponse>(res);
  },

  async getStatus(jobId: string): Promise<JobStatusResponse> {
    const res = await fetch(`/api/jobs/${jobId}`);
    return handleJson<JobStatusResponse>(res);
  },

  async getResult(jobId: string): Promise<JobResultResponse> {
    const res = await fetch(`/api/jobs/${jobId}/result`);
    return handleJson<JobResultResponse>(res);
  },

  async submitReview(jobId: string, review: UserComment): Promise<RunSubmitResponse> {
    const res = await fetch(`/api/jobs/${jobId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(review),
    });
    return handleJson<RunSubmitResponse>(res);
  },
};
