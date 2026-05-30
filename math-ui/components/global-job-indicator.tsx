"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import {
  getAllActiveJobs,
  clearAllActiveJobs,
  type ActiveJobEntry,
  type ActiveJobType,
} from "@/lib/platform";

const POLL_MS = 2000;
const DONE_DISPLAY_MS = 5000;

const JOB_LABELS: Record<ActiveJobType, string> = {
  math_qa: "Math Q&A",
  math_conversation: "Math Conversation",
};

const JOB_LINKS: Record<ActiveJobType, (entry: ActiveJobEntry) => string> = {
  math_qa: (e) => (e.entityId ? `/math-qa/${e.entityId}` : "/"),
  math_conversation: (e) => (e.entityId ? `/math-conversation/${e.entityId}` : "/"),
};

interface DoneEntry {
  jobType: ActiveJobType;
  label: string;
  link: string;
  expiresAt: number;
}

export function GlobalJobIndicator() {
  const [allJobs, setAllJobs] = useState<ActiveJobEntry[]>([]);
  const [doneList, setDoneList] = useState<DoneEntry[]>([]);
  const [open, setOpen] = useState(false);
  const prevKeys = useRef<Set<string>>(new Set());

  const tick = useCallback(() => {
    const jobs = getAllActiveJobs();
    const currentKeys = new Set(jobs.map((j) => `${j.jobType}::${j.entityId ?? ""}`));
    const now = Date.now();
    const newDone: DoneEntry[] = [];

    for (const key of prevKeys.current) {
      if (!currentKeys.has(key)) {
        const [jobType, entityId] = key.split("::") as [ActiveJobType, string | undefined];
        const fakeEntry = { jobType, entityId } as ActiveJobEntry;
        newDone.push({
          jobType,
          label: JOB_LABELS[jobType] ?? jobType,
          link: JOB_LINKS[jobType]?.(fakeEntry) ?? "/",
          expiresAt: now + DONE_DISPLAY_MS,
        });
      }
    }

    prevKeys.current = currentKeys;
    setAllJobs(jobs);

    if (newDone.length > 0) {
      setDoneList((prev) => [...prev.filter((d) => d.expiresAt > now), ...newDone]);
      setOpen(true);
    } else {
      setDoneList((prev) => {
        const filtered = prev.filter((d) => d.expiresAt > now);
        return filtered.length === prev.length ? prev : filtered;
      });
    }
  }, []);

  useEffect(() => {
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => clearInterval(id);
  }, [tick]);

  const handleDebugClear = useCallback(() => {
    if (process.env.NODE_ENV === "production") return;
    if (!window.confirm("Debug: clear local active jobs?")) return;
    clearAllActiveJobs();
    prevKeys.current = new Set();
    setDoneList([]);
    setAllJobs([]);
  }, []);

  const running = allJobs.filter((j) => j.status !== "waiting_input");
  const waiting = allJobs.filter((j) => j.status === "waiting_input");
  const runningCount = running.length;
  const waitingCount = waiting.length;
  const count = allJobs.length;
  const hasDone = doneList.length > 0;
  const hasAnything = count > 0 || hasDone;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="fixed right-0 top-1/2 z-50 -translate-y-1/2 flex flex-col items-center gap-2 rounded-l-xl border border-r-0 px-2.5 py-4 shadow-xl transition-all hover:px-3"
        style={{
          background: hasAnything ? "var(--color-surface-elevated)" : "var(--color-surface)",
          borderColor: runningCount > 0
            ? "var(--color-primary)"
            : waitingCount > 0
              ? "var(--color-warning, #f59e0b)"
              : hasDone
                ? "var(--color-success)"
                : "var(--color-border)",
        }}
        aria-label={open ? "Close job panel" : "Open job panel"}
      >
        {runningCount > 0 ? (
          <span className="relative flex h-3.5 w-3.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex h-3.5 w-3.5 rounded-full bg-primary" />
          </span>
        ) : waitingCount > 0 ? (
          <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full" style={{ background: "var(--color-warning, #f59e0b)" }}>
            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="4"><path d="M12 9v4M12 17h.01" /></svg>
          </span>
        ) : hasDone ? (
          <span className="flex h-3.5 w-3.5 rounded-full bg-[var(--color-success)]" />
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-muted">
            <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
          </svg>
        )}
        <span
          className="font-bold uppercase tracking-widest"
          style={{
            writingMode: "vertical-rl",
            fontSize: count > 0 ? 11 : 10,
            letterSpacing: "0.12em",
            color: runningCount > 0
              ? "var(--color-primary)"
              : waitingCount > 0
                ? "var(--color-warning, #f59e0b)"
                : hasDone
                  ? "var(--color-success)"
                  : "var(--color-text-muted)",
          }}
        >
          {runningCount > 0 ? `${runningCount} JOB${runningCount > 1 ? "S" : ""}` : waitingCount > 0 ? "REVIEW" : hasDone ? "DONE" : "JOBS"}
        </span>
      </button>

      <div
        className="fixed right-0 top-0 z-40 h-full w-72 border-l border-border bg-surface shadow-2xl transition-transform duration-200 ease-in-out flex flex-col"
        style={{ transform: open ? "translateX(0)" : "translateX(100%)" }}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-text">Jobs</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDebugClear}
              className="rounded-md px-2 py-1 text-[11px] font-semibold text-text-muted hover:bg-surface-elevated hover:text-text transition-colors"
              style={{ display: process.env.NODE_ENV === "production" ? "none" : undefined }}
              title="Debug: clear local active jobs"
            >
              Clear Local
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md p-1 text-text-muted hover:bg-surface-elevated hover:text-text transition-colors"
              aria-label="Close"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {!hasAnything && (
            <div className="flex flex-col items-center justify-center h-full px-4 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-elevated mb-3">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-muted">
                  <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                </svg>
              </div>
              <p className="text-sm text-text-muted">No jobs running</p>
              <p className="mt-1 text-xs text-text-muted/70">Submit a math question to get started.</p>
            </div>
          )}

          {runningCount > 0 && (
            <div className="px-3 pt-3 pb-1">
              <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Running</p>
              <div className="space-y-1">
                {running.map((job) => (
                  <Link
                    key={`run-${job.jobType}::${job.entityId ?? ""}`}
                    href={JOB_LINKS[job.jobType]?.(job) ?? "/"}
                    onClick={() => setOpen(false)}
                    className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors hover:bg-surface-elevated group"
                  >
                    <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                    <div className="min-w-0 flex-1">
                      <p className="text-text font-medium truncate text-xs group-hover:text-primary transition-colors">{JOB_LABELS[job.jobType]}</p>
                      <p className="text-[10px] text-text-muted">Started {formatAge(job.timestamp)}</p>
                    </div>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-text-muted/40">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {waitingCount > 0 && (
            <div className="px-3 pt-3 pb-1">
              <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--color-warning, #f59e0b)" }}>
                Needs your review
              </p>
              <div className="space-y-1">
                {waiting.map((job) => (
                  <Link
                    key={`wait-${job.jobType}::${job.entityId ?? ""}`}
                    href={JOB_LINKS[job.jobType]?.(job) ?? "/"}
                    onClick={() => setOpen(false)}
                    className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors hover:bg-surface-elevated group"
                  >
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full" style={{ background: "var(--color-warning, #f59e0b)" }}>
                      <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="4"><path d="M12 9v4M12 17h.01" /></svg>
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium truncate" style={{ color: "var(--color-warning, #f59e0b)" }}>{JOB_LABELS[job.jobType]}</p>
                      <p className="text-[10px] text-text-muted">Awaiting your input</p>
                    </div>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-text-muted/40">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {hasDone && (
            <div className="px-3 pt-3 pb-1">
              <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Just finished</p>
              <div className="space-y-1">
                {doneList.map((d, i) => (
                  <Link
                    key={`done-${d.jobType}-${i}`}
                    href={d.link}
                    onClick={() => setOpen(false)}
                    className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors hover:bg-surface-elevated group"
                  >
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--color-success)]/15">
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" strokeWidth="3"><path d="M20 6L9 17l-5-5" /></svg>
                    </span>
                    <p className="text-xs font-medium text-[var(--color-success)] truncate flex-1">{d.label} completed</p>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-text-muted/40">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {open && <div className="fixed inset-0 z-30 bg-black/10 pointer-events-none" />}
    </>
  );
}

function formatAge(timestamp: number): string {
  const sec = Math.floor((Date.now() - timestamp) / 1000);
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.floor(min / 60)}h ago`;
}
