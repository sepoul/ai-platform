import Link from "next/link";
import {
  listArtifactTypes,
  listCodePackages,
  listJobDefinitions,
} from "@/lib/api/catalogs";
import { fmtTimestamp } from "@/lib/format";

export const dynamic = "force-dynamic";

type Card = {
  title: string;
  count: number;
  href: string;
  lastDeployed: string | undefined;
  blurb: string;
};

export default async function OverviewPage() {
  const [jds, ats, cps] = await Promise.all([
    listJobDefinitions(),
    listArtifactTypes(),
    listCodePackages(),
  ]);

  const cards: Card[] = [
    {
      title: "Job Definitions",
      count: jds.length,
      href: "/job-definitions",
      lastDeployed: jds[0]?.deployed_at,
      blurb: "Runnable jobs the platform knows about.",
    },
    {
      title: "Artifact Types",
      count: ats.length,
      href: "/artifact-types",
      lastDeployed: ats[0]?.deployed_at,
      blurb: "Typed outputs a job can produce.",
    },
    {
      title: "Code Packages",
      count: cps.length,
      href: "/code-packages",
      lastDeployed: cps[0]?.deployed_at,
      blurb: "Installable wheels that back a JobDefinition.",
    },
  ];

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Control plane</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Snapshot of what's deployed on this ai-platform instance.
          Bundle deploys (`aiplatform deploy`) and boot-time auto-deploy
          write into these three catalogs.
        </p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {cards.map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className="rounded-md border border-[var(--border)] bg-[var(--background)] p-5 transition-colors hover:bg-[var(--muted)]"
          >
            <div className="text-xs uppercase tracking-wide text-[var(--muted-foreground)]">
              {c.title}
            </div>
            <div className="mt-2 text-3xl font-semibold">{c.count}</div>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">
              {c.blurb}
            </p>
            <div className="mt-3 text-xs text-[var(--muted-foreground)]">
              Last deploy: {fmtTimestamp(c.lastDeployed)}
            </div>
          </Link>
        ))}
      </section>
    </div>
  );
}
