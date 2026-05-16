/**
 * Platform job-lifecycle types — derived from the OpenAPI schema.
 *
 * No domain-specific shapes leak into this file: `JobStatusResponse.result`
 * is typed as `unknown` so the platform stays domain-agnostic. Domain
 * code narrows it (e.g. via `jobsClient.getResult` returning a typed
 * `JobResultResponse`).
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

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
  Omit<S["JobStatusResponse"], "status" | "result">,
  "stage" | "percent" | "message" | "waiting_for" | "error_message"
> & {
  status: JobStatus;
  // The platform stays domain-agnostic — narrow at the consumer.
  result: unknown;
};

export type RunSubmitResponse = S["RunSubmitResponse"];

// `result` is pydantic-optional but the GET endpoint always populates
// the field — tighten to `T | null`, never `undefined`.
export type JobResultResponse = Required_<S["JobResultResponse"], "result">;

export type UserComment = S["UserComment"];
