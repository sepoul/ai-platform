"use client";

import { useEffect, useRef } from "react";
import { Radio } from "lucide-react";
import { useJobLogs, type LogEntry } from "@/lib/platform";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Live worker log panel. Subscribes to `/api/jobs/{jobId}/logs/stream`
 * (SSE) and appends entries as they arrive. Designed to sit next to
 * the workflow runner so the user sees what the worker is doing in
 * real time.
 *
 * `enabled` lets the parent stop the subscription once the job is
 * terminal — saves a hanging connection.
 */
export function JobLogs({
  jobId,
  enabled = true,
  className,
}: {
  jobId: string;
  enabled?: boolean;
  className?: string;
}) {
  const { entries, connected, error } = useJobLogs(jobId, enabled);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to the latest entry. Only when the user is already
  // near the bottom — don't fight a user reading older entries.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const nearBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    if (nearBottom) node.scrollTop = node.scrollHeight;
  }, [entries.length]);

  return (
    <Card className={className}>
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Worker logs
          </p>
          <ConnectionPill connected={connected} error={error} enabled={enabled} />
        </div>

        <div
          ref={scrollRef}
          className="max-h-72 overflow-auto rounded-md border bg-muted/40 px-3 py-2"
        >
          {entries.length === 0 ? (
            <p className="text-xs italic text-muted-foreground">
              {enabled
                ? "waiting for the worker to say something…"
                : "stream stopped"}
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5 font-mono text-[11.5px] leading-relaxed">
              {entries.map((e, i) => (
                <LogRow key={i} entry={e} />
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function LogRow({ entry }: { entry: LogEntry }) {
  const levelClass = LEVEL_CLASS[entry.level] ?? "text-muted-foreground";
  return (
    <li className="flex items-baseline gap-2">
      <span className="shrink-0 text-muted-foreground/70">
        {formatClock(entry.timestamp)}
      </span>
      <span className={cn("shrink-0 uppercase", levelClass)}>
        {entry.level}
      </span>
      {entry.stage && (
        <span className="shrink-0 text-primary/80">{entry.stage}</span>
      )}
      <span className="min-w-0 flex-1 break-words text-foreground">
        {entry.message}
      </span>
    </li>
  );
}

function ConnectionPill({
  connected,
  error,
  enabled,
}: {
  connected: boolean;
  error: string | null;
  enabled: boolean;
}) {
  if (!enabled) {
    return (
      <Badge variant="outline" className="gap-1 text-[10px]">
        idle
      </Badge>
    );
  }
  if (connected) {
    return (
      <Badge
        variant="outline"
        className="gap-1 border-[var(--success)]/40 bg-[var(--success)]/10 text-[10px] text-[var(--success)]"
      >
        <Radio className="size-3 animate-pulse" />
        live
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="gap-1 text-[10px] text-muted-foreground">
      {error ? "reconnecting…" : "connecting…"}
    </Badge>
  );
}

const LEVEL_CLASS: Record<LogEntry["level"], string> = {
  info: "text-muted-foreground",
  warning: "text-[var(--warning)]",
  error: "text-destructive",
  debug: "text-muted-foreground/60",
};

function formatClock(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso.slice(11, 19);
  }
}

