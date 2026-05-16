"use client";

import { useEffect, useState } from "react";
import type { LogEntry } from "@/lib/platform/log-types";

/**
 * Subscribes to `/api/jobs/{jobId}/logs/stream` via `EventSource`
 * (SSE). Keeps an append-only buffer of entries; resets on jobId
 * change. Closes the connection on unmount and on terminal status —
 * call sites that already track terminal state can pass `enabled` to
 * stop polling.
 */
export function useJobLogs(jobId: string | null, enabled: boolean = true) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntries([]);
    setError(null);
    setConnected(false);

    if (!jobId || !enabled) return;
    if (typeof window === "undefined") return;

    const url = `/api/jobs/${encodeURIComponent(jobId)}/logs/stream`;
    const source = new EventSource(url);

    source.onopen = () => setConnected(true);

    source.onmessage = (ev) => {
      try {
        const entry = JSON.parse(ev.data) as LogEntry;
        setEntries((prev) => [...prev, entry]);
      } catch {
        // Skip malformed events — don't kill the stream over one bad line.
      }
    };

    source.onerror = () => {
      // EventSource auto-reconnects on transient failures; flag it
      // visually rather than tearing the subscription down.
      setConnected(false);
      setError("connection lost (will retry)");
    };

    return () => {
      source.close();
    };
  }, [jobId, enabled]);

  return { entries, connected, error };
}
