import Link from "next/link";
import { notFound } from "next/navigation";
import { StatusBadge } from "@/components/StatusBadge";
import { getJob, getJobResult } from "@/lib/api/jobs";
import { fmtTimestamp } from "@/lib/format";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ job_id: string }> };

const STATUS_HAS_RESULT = new Set(["SUCCEEDED", "WAITING_INPUT"]);

export default async function JobDetailPage({ params }: Props) {
  const { job_id } = await params;

  let status;
  try {
    status = await getJob(job_id);
  } catch {
    notFound();
  }

  // Only fetch the result when the status allows — saves an API call
  // for PENDING/RUNNING/FAILED and keeps the page deterministic.
  const result = STATUS_HAS_RESULT.has(status.status)
    ? await getJobResult(job_id)
    : null;

  return (
    <div>
      <header className="mb-6">
        <div className="mb-1 text-sm">
          <Link href="/jobs" className="text-[var(--accent)] hover:underline">
            ← All jobs
          </Link>
        </div>
        <h1 className="mono text-xl font-semibold break-all">{job_id}</h1>
      </header>

      <section className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Type" value={status.job_type} mono />
        <Field
          label="Status"
          value={<StatusBadge status={status.status} />}
        />
        <Field label="Stage" value={status.stage ?? "—"} />
        <Field
          label="Percent"
          value={status.percent != null ? `${status.percent}%` : "—"}
        />
        <Field label="Created" value={fmtTimestamp(status.created_at)} />
        <Field
          label="Waiting for"
          value={status.waiting_for ?? "—"}
        />
      </section>

      {status.message && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-medium text-[var(--muted-foreground)]">
            Message
          </h2>
          <div className="rounded-md border border-[var(--border)] bg-[var(--muted)] p-3 text-sm">
            {status.message}
          </div>
        </section>
      )}

      {status.error_message && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-medium text-[var(--muted-foreground)]">
            Error
          </h2>
          <pre className="mono overflow-auto rounded-md border border-red-200 bg-red-50 p-3 text-xs leading-relaxed text-red-900 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
            {status.error_message}
          </pre>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-medium text-[var(--muted-foreground)]">
          Result
        </h2>
        {result ? (
          <pre className="mono overflow-auto rounded-md border border-[var(--border)] bg-[var(--muted)] p-3 text-xs leading-relaxed">
            {JSON.stringify(result.result ?? null, null, 2)}
          </pre>
        ) : (
          <div className="rounded-md border border-[var(--border)] bg-[var(--muted)] p-3 text-sm text-[var(--muted-foreground)]">
            No result available yet — job is {status.status}.
          </div>
        )}
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="text-xs uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className={`mt-1 text-sm ${mono ? "mono" : ""}`}>{value}</div>
    </div>
  );
}
