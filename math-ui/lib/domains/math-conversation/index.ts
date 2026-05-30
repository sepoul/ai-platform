/**
 * Math Conversation domain — typed shapes, submit client, and the live
 * `CrewChatEvent` stream hook for the `math_conversation` workflow.
 * Built on top of `@/lib/platform`; the platform never imports from
 * this module.
 */
export type {
  MathConversationInput,
  MathConversationArtifact,
  MathConversationResult,
  ConversationTurn,
  ToolCallRecord,
  CrewChatEvent,
  CrewChatEventKind,
} from "./types";

export { conversationClient } from "./client";

export { useCrewChatStream, parseCrewChatEvent } from "./hooks";
export type { CrewChatStream } from "./hooks";
