/** Format an ISO timestamp into a compact "YYYY-MM-DD HH:MM:SS" UTC string. */
export function fmtTimestamp(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

/** Compact bytes display (KB / MB). */
export function fmtBytes(n: number | undefined | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

/** Shorten a sha256 to its first 12 hex chars + ellipsis. */
export function fmtSha(sha: string | undefined | null): string {
  if (!sha) return "—";
  return sha.length > 12 ? `${sha.slice(0, 12)}…` : sha;
}
