"use client";

import { useState } from "react";

export type Column<T> = {
  header: string;
  cell: (row: T) => React.ReactNode;
  width?: string; // tailwind class, e.g. "w-1/4"
};

type Props<T> = {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  /** Optional: render the right-side drawer for a selected row. */
  emptyMessage?: string;
};

export function CatalogTable<T>({
  rows,
  columns,
  rowKey,
  emptyMessage = "No rows.",
}: Props<T>) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected = rows.find((r) => rowKey(r) === selectedKey) ?? null;

  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-[var(--border)] bg-[var(--muted)] p-6 text-center text-sm text-[var(--muted-foreground)]">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_24rem]">
      <div className="overflow-hidden rounded-md border border-[var(--border)]">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-[var(--muted)] text-left text-[var(--muted-foreground)]">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.header}
                  className={`px-3 py-2 font-medium ${c.width ?? ""}`}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const key = rowKey(row);
              const isSelected = key === selectedKey;
              return (
                <tr
                  key={key}
                  onClick={() => setSelectedKey(isSelected ? null : key)}
                  className={`cursor-pointer border-t border-[var(--border)] transition-colors ${
                    isSelected
                      ? "bg-[var(--muted)]"
                      : "hover:bg-[var(--muted)]"
                  }`}
                >
                  {columns.map((c) => (
                    <td key={c.header} className="px-3 py-2 align-top">
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <aside className="rounded-md border border-[var(--border)] bg-[var(--muted)] p-4">
        {selected ? (
          <>
            <div className="mb-2 text-xs uppercase tracking-wide text-[var(--muted-foreground)]">
              Record JSON
            </div>
            <pre className="mono overflow-auto rounded bg-[var(--background)] p-3 text-xs leading-relaxed">
              {JSON.stringify(selected, null, 2)}
            </pre>
          </>
        ) : (
          <div className="text-sm text-[var(--muted-foreground)]">
            Click a row to inspect the full record.
          </div>
        )}
      </aside>
    </div>
  );
}
