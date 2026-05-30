"use client";

import { useMemo } from "react";
import { useJobLogs } from "@/lib/platform";
import type { LogEntry } from "@/lib/platform";
import type { CrewChatEvent } from "./types";

/**
 * `crew_chat` source tag the worker stamps on `CrewChatEmitter`
 * output. Mirrors `CREW_CHAT_SOURCE` in
 * `mathai/math_conversation/crew/callbacks.py`.
 */
const CREW_CHAT_SOURCE = "crew_chat";

/**
 * Try to interpret a log entry's `message` as a `CrewChatEvent`. Returns
 * `null` for plain log lines (worker.info, errors, etc.) so the view
 * can render them in a separate stream if it wants.
 *
 * Detection is JSON-shape + the `event` discriminator. The `source`
 * tag is a strong hint (always `crew_chat` for our emitter) but we
 * don't require it — the backend tags are best-effort and the JSON
 * shape is the authoritative check.
 */
export function parseCrewChatEvent(entry: LogEntry): CrewChatEvent | null {
  if (!entry.message || (entry.message[0] !== "{" && entry.message[0] !== "[")) {
    return null;
  }
  try {
    const parsed = JSON.parse(entry.message) as Partial<CrewChatEvent>;
    if (parsed && typeof parsed === "object" && typeof parsed.event === "string") {
      return parsed as CrewChatEvent;
    }
  } catch {
    // Not JSON, or not an object — definitely not a crew event.
  }
  return null;
}

export interface CrewChatStream {
  /** Typed crew-chat events, in arrival order. */
  events: CrewChatEvent[];
  /** Log entries that did NOT parse as crew events (plain worker logs). */
  plainLogs: LogEntry[];
  connected: boolean;
  error: string | null;
}

/**
 * Subscribes to `/jobs/{jobId}/logs/stream` and splits the entries into
 * typed `CrewChatEvent`s vs everything else. `enabled` defaults to
 * `true`; the caller passes `false` once the job reaches a terminal
 * status to stop streaming.
 */
export function useCrewChatStream(
  jobId: string | null,
  enabled: boolean = true,
): CrewChatStream {
  const { entries, connected, error } = useJobLogs(jobId, enabled);

  return useMemo(() => {
    const events: CrewChatEvent[] = [];
    const plainLogs: LogEntry[] = [];
    for (const entry of entries) {
      // Fast path: anything tagged `crew_chat` is a candidate; otherwise
      // shape-check defensively (an emitter without the tag still parses).
      const event = entry.source === CREW_CHAT_SOURCE
        ? parseCrewChatEvent(entry)
        : parseCrewChatEvent(entry);
      if (event) events.push(event);
      else plainLogs.push(entry);
    }
    return { events, plainLogs, connected, error };
  }, [entries, connected, error]);
}
