"use client";

import { useRouter, useSearchParams } from "next/navigation";

const STATUSES = ["", "PENDING", "RUNNING", "SUCCEEDED", "FAILED", "WAITING_INPUT", "CANCELLED"];

export function StatusFilter() {
  const router = useRouter();
  const params = useSearchParams();
  const current = params.get("status") ?? "";

  return (
    <div className="flex items-center gap-1 text-sm">
      <span className="text-[var(--muted-foreground)]">Status:</span>
      {STATUSES.map((s) => {
        const label = s || "all";
        const active = s === current;
        const href = s ? `?status=${s}` : "/jobs";
        return (
          <button
            key={label}
            onClick={() => router.push(href)}
            className={`rounded px-2 py-1 transition-colors ${
              active
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "hover:bg-[var(--muted)]"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
