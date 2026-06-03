"use client";

import { CatalogTable, type Column } from "@/components/CatalogTable";
import type { CodePackageRecord } from "@/lib/api/catalogs";
import { fmtBytes, fmtSha, fmtTimestamp } from "@/lib/format";

const COLUMNS: Column<CodePackageRecord>[] = [
  { header: "Name", cell: (r) => <span className="mono">{r.name}</span>, width: "w-1/5" },
  { header: "Version", cell: (r) => <span className="mono">{r.version}</span>, width: "w-24" },
  { header: "Runtime", cell: (r) => r.runtime_selector, width: "w-28" },
  { header: "Size", cell: (r) => fmtBytes(r.size_bytes), width: "w-20" },
  {
    header: "sha256",
    cell: (r) => <span className="mono text-xs">{fmtSha(r.sha256)}</span>,
    width: "w-36",
  },
  {
    header: "Download",
    cell: (r) => (
      <a
        href={`/api/code-packages/${encodeURIComponent(r.id)}/download`}
        className="text-[var(--accent)] hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        {r.filename}
      </a>
    ),
  },
  { header: "Deployed", cell: (r) => fmtTimestamp(r.deployed_at), width: "w-44" },
];

export function CodePackagesTable({ rows }: { rows: CodePackageRecord[] }) {
  return <CatalogTable rows={rows} columns={COLUMNS} rowKey={(r) => r.id} />;
}
