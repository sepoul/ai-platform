import { CatalogTable, type Column } from "@/components/CatalogTable";
import { listJobDefinitions, type JobDefinitionRecord } from "@/lib/api/catalogs";
import { fmtTimestamp } from "@/lib/format";

export const dynamic = "force-dynamic";

const COLUMNS: Column<JobDefinitionRecord>[] = [
  { header: "Name", cell: (r) => <span className="mono">{r.name}</span>, width: "w-1/5" },
  { header: "Version", cell: (r) => <span className="mono">{r.version}</span>, width: "w-24" },
  { header: "Runtime", cell: (r) => r.runtime_selector, width: "w-28" },
  { header: "Entrypoint", cell: (r) => <span className="mono text-xs">{r.code_entrypoint}</span> },
  { header: "Deployed", cell: (r) => fmtTimestamp(r.deployed_at), width: "w-44" },
];

export default async function JobDefinitionsPage() {
  const rows = await listJobDefinitions();
  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Job Definitions</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Runnable jobs registered on the platform. Each row carries its
          input + result JSON Schema and the code entrypoint a worker
          resolves at run time.
        </p>
      </header>
      <CatalogTable rows={rows} columns={COLUMNS} rowKey={(r) => r.id} />
    </div>
  );
}
