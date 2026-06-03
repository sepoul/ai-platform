import { CodePackagesTable } from "@/components/CodePackagesTable";
import { listCodePackages } from "@/lib/api/catalogs";

export const dynamic = "force-dynamic";

export default async function CodePackagesPage() {
  const rows = await listCodePackages();
  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Code Packages</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Installable wheels that back a JobDefinition's `code_entrypoint`.
          Each row carries the sha256-verified blob the worker fetches +
          pip-installs on boot.
        </p>
      </header>
      <CodePackagesTable rows={rows} />
    </div>
  );
}
