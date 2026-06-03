import { ArtifactTypesTable } from "@/components/ArtifactTypesTable";
import { listArtifactTypes } from "@/lib/api/catalogs";

export const dynamic = "force-dynamic";

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
      <ArtifactTypesTable rows={rows} />
    </div>
  );
}
