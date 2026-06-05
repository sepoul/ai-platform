/**
 * Thin wrapper over `@aiplatform/sdk`'s `PlatformSession`.
 */
import { platformSession } from "@/lib/session";
import type {
  WorkflowJobType,
  WorkflowListResponse,
  WorkflowSpecResponse,
} from "./workflow-types";

export function fetchWorkflows(): Promise<WorkflowListResponse> {
  return platformSession().listWorkflows();
}

export function fetchWorkflowSpec(
  jobType: WorkflowJobType
): Promise<WorkflowSpecResponse> {
  return platformSession().getWorkflowSpec(jobType);
}
