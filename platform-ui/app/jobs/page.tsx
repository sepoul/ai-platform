import { JobsTable } from "@/components/JobsTable";
import { StatusFilter } from "@/components/StatusFilter";
import { listJobs } from "@/lib/api/jobs";

export const dynamic = "force-dynamic";

type Props = {
  searchParams: Promise<{ status?: string; job_type?: string }>;
};

export default async function JobsPage({ searchParams }: Props) {
  const params = await searchParams;
  const rows = await listJobs({
    status: params.status || undefined,
    job_type: params.job_type || undefined,
    limit: 100, // API enforces le=100; pagination is a follow-up.
  });

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Run-time history. Click any job_id to inspect its status,
          stage, and (when available) result.
        </p>
      </header>
      <div className="mb-4">
        <StatusFilter />
      </div>
      <JobsTable rows={rows} />
    </div>
  );
}
