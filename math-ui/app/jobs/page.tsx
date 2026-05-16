"use client";

import { useEffect, useMemo, useState } from "react";
import {
  fetchJobs,
  TERMINAL_JOB_STATUSES,
  type JobStatus,
  type JobStatusResponse,
} from "@/lib/platform";
import {
  EmptyCard,
  ErrorCard,
  LinkCard,
  LoadingCard,
  PageContainer,
  PageHeader,
} from "@/components/library";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const ALL = "__all__";

// Tab order — running states first, terminal states after.
const STATUS_TABS: JobStatus[] = [
  "RUNNING",
  "WAITING_INPUT",
  "PENDING",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
];

const STATUS_BADGE_CLASS: Record<string, string> = {
  PENDING: "bg-muted text-muted-foreground",
  RUNNING: "bg-primary/15 text-primary",
  WAITING_INPUT:
    "bg-[var(--warning)]/15 text-[var(--warning)] border-[var(--warning)]/30",
  SUCCEEDED:
    "bg-[var(--success)]/15 text-[var(--success)] border-[var(--success)]/30",
  FAILED: "bg-destructive/15 text-destructive border-destructive/30",
  CANCELLED: "bg-muted text-muted-foreground",
};

/**
 * Job history index — every run, newest first. Domain-specific
 * detail pages handle full result rendering (currently only
 * `/math-qa/[jobId]`); rows for unknown job types stay informational.
 */
export default function JobsPage() {
  const [jobs, setJobs] = useState<JobStatusResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchJobs({ limit: 100 })
      .then((res) => {
        if (!cancelled) setJobs(res);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = useMemo(() => groupByStatus(jobs ?? []), [jobs]);

  return (
    <PageContainer>
      <PageHeader
        title="Jobs"
        subtitle="Every workflow run that's been submitted. This is the history view; the workflows themselves (definitions) live under /workflows."
      />

      {error && <ErrorCard>{error}</ErrorCard>}
      {!jobs && !error && <LoadingCard rows={6} />}
      {jobs && jobs.length === 0 && (
        <EmptyCard>No jobs yet — submit one from a workflow.</EmptyCard>
      )}

      {jobs && jobs.length > 0 && (
        <Tabs defaultValue={ALL} className="gap-4">
          <TabsList className="h-auto flex-wrap justify-start gap-1 bg-transparent p-0">
            <TabTriggerWithCount value={ALL} label="All" count={jobs.length} />
            {STATUS_TABS.filter((s) => grouped[s]?.length > 0).map((s) => (
              <TabTriggerWithCount
                key={s}
                value={s}
                label={s.replace("_", " ").toLowerCase()}
                count={grouped[s].length}
              />
            ))}
          </TabsList>

          <TabsContent value={ALL} className="mt-0">
            <JobRows rows={jobs} />
          </TabsContent>
          {STATUS_TABS.filter((s) => grouped[s]?.length > 0).map((s) => (
            <TabsContent key={s} value={s} className="mt-0">
              <JobRows rows={grouped[s]} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </PageContainer>
  );
}

function TabTriggerWithCount({
  value,
  label,
  count,
}: {
  value: string;
  label: string;
  count: number;
}) {
  return (
    <TabsTrigger
      value={value}
      className="data-[state=active]:bg-secondary data-[state=active]:shadow-sm gap-1.5 rounded-md border border-transparent px-3 py-1.5 text-xs font-medium text-muted-foreground capitalize hover:text-foreground data-[state=active]:border-border data-[state=active]:text-foreground"
    >
      <span>{label}</span>
      <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground">
        {count}
      </span>
    </TabsTrigger>
  );
}

function JobRows({ rows }: { rows: JobStatusResponse[] }) {
  if (rows.length === 0) {
    return <EmptyCard>No jobs in this state.</EmptyCard>;
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((job) => {
        const href = jobDetailHref(job);
        const inner = <JobRowBody job={job} />;
        return href ? (
          <LinkCard key={job.job_id} href={href} contentClassName="px-4 py-3">
            {inner}
          </LinkCard>
        ) : (
          <div
            key={job.job_id}
            className="rounded-lg border bg-card px-4 py-3 ring-1 ring-foreground/8"
          >
            {inner}
          </div>
        );
      })}
    </div>
  );
}

function JobRowBody({ job }: { job: JobStatusResponse }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Badge
        variant="outline"
        className={cn(
          "px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
          STATUS_BADGE_CLASS[job.status] ?? "bg-muted text-muted-foreground"
        )}
      >
        {job.status.replace("_", " ").toLowerCase()}
      </Badge>
      <Badge variant="secondary" className="font-mono text-[11px]">
        {job.job_type}
      </Badge>
      <span className="font-mono text-xs">{job.job_id}</span>
      {job.stage && !TERMINAL_JOB_STATUSES.includes(job.status) && (
        <span className="font-mono text-[11px] text-muted-foreground">
          @ {job.stage}
        </span>
      )}
      <span className="ml-auto text-xs text-muted-foreground">
        {new Date(job.created_at).toLocaleString()}
      </span>
    </div>
  );
}

function groupByStatus(
  jobs: JobStatusResponse[]
): Record<string, JobStatusResponse[]> {
  const out: Record<string, JobStatusResponse[]> = {};
  for (const j of jobs) {
    (out[j.status] ??= []).push(j);
  }
  return out;
}

// Domain-specific detail routes. For job types without a dedicated
// page, the row stays inert (no link) — when the next domain ships,
// add its mapping here.
const JOB_TYPE_ROUTES: Record<string, (jobId: string) => string> = {
  math_qa: (jobId) => `/math-qa/${encodeURIComponent(jobId)}`,
};

function jobDetailHref(job: JobStatusResponse): string | null {
  const builder = JOB_TYPE_ROUTES[job.job_type];
  return builder ? builder(job.job_id) : null;
}
