"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { type Field, buildSubmission, compileSchema } from "@/lib/schemaForm";

type Props = {
  jobType: string; // for the submission body's job_type discriminator
  jobName: string; // display + redirect target
  inputSchema: unknown;
};

export function SubmitJobForm({ jobType, jobName, inputSchema }: Props) {
  const router = useRouter();
  const fields = compileSchema(inputSchema);
  const initial: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.kind === "hidden") continue;
    if ("default" in f && f.default !== undefined) {
      initial[f.name] = f.default;
    }
  }
  // Ensure job_type makes it into the body even if the schema didn't
  // emit it as a `const`.
  initial.job_type = jobType;

  const [values, setValues] = useState<Record<string, unknown>>(initial);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const body = buildSubmission(fields, values);
      body.job_type = jobType;
      const resp = await fetch("/api/jobs/runs/submit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status}: ${text}`);
      }
      const data: { job_id: string } = await resp.json();
      router.push(`/jobs/${data.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {fields.map((f) => f.kind === "hidden" ? null : (
        <FormField
          key={f.name}
          field={f}
          value={values[f.name]}
          onChange={(v) => setValues((prev) => ({ ...prev, [f.name]: v }))}
        />
      ))}

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
        >
          {submitting ? "Submitting…" : `Submit ${jobName} job`}
        </button>
        <span className="text-xs text-[var(--muted-foreground)]">
          POST /jobs/runs/submit
        </span>
      </div>
    </form>
  );
}

function FormField({
  field,
  value,
  onChange,
}: {
  field: Exclude<Field, { kind: "hidden" }>;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const labelClasses =
    "block text-sm font-medium text-[var(--foreground)] mb-1";
  const helpClasses =
    "mt-1 text-xs text-[var(--muted-foreground)]";
  const inputClasses =
    "w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]";

  return (
    <div>
      <label className={labelClasses}>
        {field.label}
        {field.required && <span className="ml-1 text-red-500">*</span>}
      </label>

      {field.kind === "string" && (
        <input
          type="text"
          className={inputClasses}
          required={field.required}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {field.kind === "text" && (
        <textarea
          className={`${inputClasses} font-normal`}
          required={field.required}
          rows={4}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {field.kind === "integer" && (
        <input
          type="number"
          className={inputClasses}
          required={field.required}
          min={field.minimum}
          max={field.maximum}
          value={(value as number | "") ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {field.kind === "boolean" && (
        <input
          type="checkbox"
          className="h-4 w-4"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      )}

      {field.kind === "json" && (
        <>
          <textarea
            className={`${inputClasses} mono text-xs`}
            required={field.required}
            rows={6}
            placeholder="Raw JSON for this field — schema fallback"
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
          />
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-[var(--muted-foreground)]">
              field schema
            </summary>
            <pre className="mono mt-1 overflow-auto rounded bg-[var(--muted)] p-2">
              {JSON.stringify(field.schema, null, 2)}
            </pre>
          </details>
        </>
      )}

      {field.description && <p className={helpClasses}>{field.description}</p>}
    </div>
  );
}
