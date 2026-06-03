import { JobDefinitionsTable } from "@/components/JobDefinitionsTable";
import { listJobDefinitions } from "@/lib/api/catalogs";

export const dynamic = "force-dynamic";

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
      <JobDefinitionsTable rows={rows} />
    </div>
  );
}
