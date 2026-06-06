/**
 * Math Conversation domain types — submit input, artifact, turn, and the
 * `CrewChatEvent` live-stream shape. Derived from the OpenAPI schema;
 * consumers should import from `@/lib/domains/math-conversation` rather
 * than reaching into the platform schema directly.
 */
import type { components } from "@aiplatform/sdk";

type S = components["schemas"];

type Required_<T, K extends keyof T> = Omit<T, K> & {
  [P in K]-?: NonNullable<T[P]>;
};

export type MathConversationInput = S["MathConversationInput"];

export type ConversationTurn = Required_<
  S["ConversationTurn"],
  "tool_calls" | "cost_usd"
>;

export type ToolCallRecord = Required_<S["ToolCallRecord"], "arguments">;

export type MathConversationArtifact = Required_<
  S["MathConversationArtifact"],
  "artifact_id" | "created_at" | "turns" | "total_cost_usd" | "stop_reason"
>;

export type MathConversationResult = Required_<
  S["MathConversationResult"],
  "artifact_refs"
> & {
  conversation: MathConversationArtifact | null;
};

/**
 * Live event the worker emits per agent action. Rides the existing
 * SSE log stream as a JSON-serialized message on a log entry tagged
 * `source="crew_chat"`. The hook in `./hooks.ts` parses log entries
 * back into this shape.
 */
export type CrewChatEvent = S["CrewChatEvent"];

export type CrewChatEventKind = NonNullable<CrewChatEvent["event"]>;
