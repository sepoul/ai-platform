"use client";

import { CatalogTable, type Column } from "@/components/CatalogTable";
import type { ArtifactTypeRecord } from "@/lib/api/catalogs";
import { fmtTimestamp } from "@/lib/format";

const COLUMNS: Column<ArtifactTypeRecord>[] = [
  { header: "Name", cell: (r) => <span className="mono">{r.name}</span>, width: "w-1/4" },
  { header: "Version", cell: (r) => <span className="mono">{r.version}</span>, width: "w-24" },
  { header: "Domain", cell: (r) => r.domain, width: "w-32" },
  { header: "Class", cell: (r) => <span className="mono text-xs">{r.class_name}</span> },
  { header: "Deployed", cell: (r) => fmtTimestamp(r.deployed_at), width: "w-44" },
];

export function ArtifactTypesTable({ rows }: { rows: ArtifactTypeRecord[] }) {
  return <CatalogTable rows={rows} columns={COLUMNS} rowKey={(r) => r.id} />;
}
