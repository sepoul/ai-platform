/**
 * Color-coded badge for a job's status string. Tailwind classes only
 * — no shadcn dep needed. Same palette across server + client so the
 * list view and the detail view stay consistent.
 */
const PALETTE: Record<string, string> = {
  PENDING:        "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  RUNNING:        "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
  SUCCEEDED:      "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200",
  FAILED:         "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
  CANCELLED:      "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  WAITING_INPUT:  "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = PALETTE[status] ?? "bg-zinc-200 text-zinc-700";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}
