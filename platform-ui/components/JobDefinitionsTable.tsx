"use client";

import Link from "next/link";
import { CatalogTable, type Column } from "@/components/CatalogTable";
import type { JobDefinitionRecord } from "@/lib/api/catalogs";
import { fmtTimestamp } from "@/lib/format";

const COLUMNS: Column<JobDefinitionRecord>[] = [
  { header: "Name", cell: (r) => <span className="mono">{r.name}</span>, width: "w-1/5" },
  { header: "Version", cell: (r) => <span className="mono">{r.version}</span>, width: "w-24" },
  { header: "Runtime", cell: (r) => r.runtime_selector, width: "w-28" },
  { header: "Entrypoint", cell: (r) => <span className="mono text-xs">{r.code_entrypoint}</span> },
  { header: "Deployed", cell: (r) => fmtTimestamp(r.deployed_at), width: "w-44" },
  {
    header: "",
    width: "w-16",
    cell: (r) => (
      <Link
        href={`/job-definitions/${encodeURIComponent(r.id)}/submit`}
        onClick={(e) => e.stopPropagation()}
        className="rounded bg-[var(--primary)] px-2 py-1 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90"
      >
        Run
      </Link>
    ),
  },
];

export function JobDefinitionsTable({ rows }: { rows: JobDefinitionRecord[] }) {
  return <CatalogTable rows={rows} columns={COLUMNS} rowKey={(r) => r.id} />;
}
