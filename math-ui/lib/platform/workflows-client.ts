import type {
  WorkflowJobType,
  WorkflowListResponse,
  WorkflowSpecResponse,
} from "./workflow-types";

async function handleJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let msg: string;
    try {
      const body = (await response.json()) as { error?: string; detail?: string };
      msg = body.error || body.detail || `HTTP ${response.status}`;
    } catch {
      msg = `HTTP ${response.status}`;
    }
    throw new Error(msg);
  }
  return response.json() as Promise<T>;
}

/**
 * Lists every domain workflow registered on the platform. Backed by
 * the platform `GET /workflows` endpoint.
 */
export async function fetchWorkflows(): Promise<WorkflowListResponse> {
  const response = await fetch("/api/workflows", {
    headers: { Accept: "application/json" },
  });
  return handleJson<WorkflowListResponse>(response);
}

/**
 * Loads the static workflow graph for a job type (stages + edges).
 * Uses the Next.js BFF route that proxies to the platform API.
 */
export async function fetchWorkflowSpec(
  jobType: WorkflowJobType
): Promise<WorkflowSpecResponse> {
  const response = await fetch(`/api/workflows/${encodeURIComponent(jobType)}`, {
    headers: { Accept: "application/json" },
  });
  return handleJson<WorkflowSpecResponse>(response);
}
