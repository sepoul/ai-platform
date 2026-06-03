import Link from "next/link";
import { notFound } from "next/navigation";
import { SubmitJobForm } from "@/components/SubmitJobForm";
import { createApiClient } from "@/lib/api/client";
import type { JobDefinitionRecord } from "@/lib/api/catalogs";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export default async function SubmitJobPage({ params }: Props) {
  const { id } = await params;
  const definitionId = decodeURIComponent(id);

  const client = createApiClient();
  const { data, error } = await client.GET("/job-definitions/{definition_id}", {
    params: { path: { definition_id: definitionId } },
  });
  if (error || !data) {
    notFound();
  }
  const jd = data as JobDefinitionRecord;

  return (
    <div className="max-w-2xl">
      <header className="mb-6">
        <div className="mb-1 text-sm">
          <Link
            href="/job-definitions"
            className="text-[var(--accent)] hover:underline"
          >
            ← Job Definitions
          </Link>
        </div>
        <h1 className="text-2xl font-semibold">Run {jd.name}</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          version <span className="mono">{jd.version}</span> ·{" "}
          runtime <span className="mono">{jd.runtime_selector}</span>
        </p>
      </header>

      <SubmitJobForm
        jobType={jd.name}
        jobName={jd.name}
        inputSchema={jd.input_schema}
      />
    </div>
  );
}
