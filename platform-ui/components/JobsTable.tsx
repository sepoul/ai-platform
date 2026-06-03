"use client";

import Link from "next/link";
import { StatusBadge } from "@/components/StatusBadge";
import type { JobStatusResponse } from "@/lib/api/jobs";
import { fmtTimestamp } from "@/lib/format";

type Props = { rows: JobStatusResponse[] };

export function JobsTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-[var(--border)] bg-[var(--muted)] p-6 text-center text-sm text-[var(--muted-foreground)]">
        No jobs matching this filter.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-md border border-[var(--border)]">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-[var(--muted)] text-left text-[var(--muted-foreground)]">
          <tr>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Job ID</th>
            <th className="px-3 py-2 font-medium">Stage</th>
            <th className="px-3 py-2 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.job_id}
              className="border-t border-[var(--border)] transition-colors hover:bg-[var(--muted)]"
            >
              <td className="px-3 py-2">
                <StatusBadge status={r.status} />
              </td>
              <td className="px-3 py-2">{r.job_type}</td>
              <td className="px-3 py-2">
                <Link
                  href={`/jobs/${r.job_id}`}
                  className="mono text-xs text-[var(--accent)] hover:underline"
                >
                  {r.job_id}
                </Link>
              </td>
              <td className="px-3 py-2 text-[var(--muted-foreground)]">
                {r.stage ?? "—"}
                {r.percent != null ? ` (${r.percent}%)` : ""}
              </td>
              <td className="px-3 py-2">{fmtTimestamp(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
