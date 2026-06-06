/**
 * Platform job-lifecycle types — re-exported from `@aiplatform/sdk`
 * with math-ui's tightening of pydantic-optional fields applied.
 *
 * No domain-specific shapes leak into this file: `JobStatusResponse.result`
 * is typed as `unknown` so the platform stays domain-agnostic. Domain
 * code narrows it (e.g. via `jobsClient.getResult` returning a typed
 * `JobResultResponse`).
 */
import type {
  JobResultResponse as SdkJobResultResponse,
  JobStatusResponse as SdkJobStatusResponse,
  RunSubmitResponse as SdkRunSubmitResponse,
  UserComment as SdkUserComment,
} from "@aiplatform/sdk";

// Pydantic-optional fields with defaults are always present at runtime;
// tighten them so consumers don't need ?? fallbacks.
type Required_<T, K extends keyof T> = Omit<T, K> & {
  [P in K]-?: NonNullable<T[P]>;
};

export type JobStatus =
  | "PENDING"
  | "RUNNING"
  | "WAITING_INPUT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export const TERMINAL_JOB_STATUSES: JobStatus[] = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
];

export type JobStatusResponse = Required_<
  Omit<SdkJobStatusResponse, "status" | "result">,
  "stage" | "percent" | "message" | "waiting_for" | "error_message"
> & {
  status: JobStatus;
  // The platform stays domain-agnostic — narrow at the consumer.
  result: unknown;
};

export type RunSubmitResponse = SdkRunSubmitResponse;

// `result` is pydantic-optional but the GET endpoint always populates
// the field — tighten to `T | null`, never `undefined`.
export type JobResultResponse = Required_<SdkJobResultResponse, "result">;

export type UserComment = SdkUserComment;
