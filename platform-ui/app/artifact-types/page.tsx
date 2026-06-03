import { CatalogTable, type Column } from "@/components/CatalogTable";
import { listArtifactTypes, type ArtifactTypeRecord } from "@/lib/api/catalogs";
import { fmtTimestamp } from "@/lib/format";

export const dynamic = "force-dynamic";

const COLUMNS: Column<ArtifactTypeRecord>[] = [
  { header: "Name", cell: (r) => <span className="mono">{r.name}</span>, width: "w-1/4" },
  { header: "Version", cell: (r) => <span className="mono">{r.version}</span>, width: "w-24" },
  { header: "Domain", cell: (r) => r.domain, width: "w-32" },
  { header: "Class", cell: (r) => <span className="mono text-xs">{r.class_name}</span> },
  { header: "Deployed", cell: (r) => fmtTimestamp(r.deployed_at), width: "w-44" },
];

export default async function ArtifactTypesPage() {
  const rows = await listArtifactTypes();
  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Artifact Types</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Typed outputs a job can produce. Each row records the JSON
          Schema of a `BaseArtifact` subclass + which domain owns it.
        </p>
      </header>
      <CatalogTable rows={rows} columns={COLUMNS} rowKey={(r) => r.id} />
    </div>
  );
}
