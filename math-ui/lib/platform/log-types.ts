/**
 * Live worker → UI log types. Mirrors `ai_platform.runtime.log_bus.LogEntry`.
 *
 * The shape is deliberately simple (no `components["schemas"]` derivation
 * yet) because the SSE stream isn't part of the OpenAPI document; the
 * upstream endpoint emits `text/event-stream`. If we ever want to
 * formalize, lift `LogEntry` into the OpenAPI schema and re-derive.
 */
export type LogLevel = "info" | "warning" | "error" | "debug";

export interface LogEntry {
  job_id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
  stage?: string | null;
  source?: string | null;
}
