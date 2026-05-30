const STORAGE_KEY = "mathai:active-jobs";
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

export type ActiveJobType = "math_qa" | "math_conversation";
export type ActiveJobStatus = "running" | "waiting_input";

export interface ActiveJobEntry {
  jobId: string;
  jobType: ActiveJobType;
  entityId?: string;
  meta?: Record<string, string>;
  status?: ActiveJobStatus;
  timestamp: number;
}

type ActiveJobMap = Record<string, ActiveJobEntry>;

function readAll(): ActiveJobMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as ActiveJobMap;
    const now = Date.now();
    let pruned = false;
    for (const key of Object.keys(parsed)) {
      if (now - parsed[key].timestamp > MAX_AGE_MS) {
        delete parsed[key];
        pruned = true;
      }
    }
    if (pruned) localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
    return parsed;
  } catch {
    return {};
  }
}

function writeAll(map: ActiveJobMap) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {}
}

export function clearAllActiveJobs(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}

function entryKey(jobType: ActiveJobType, entityId?: string): string {
  return entityId ? `${jobType}::${entityId}` : jobType;
}

export function registerActiveJob(entry: Omit<ActiveJobEntry, "timestamp">): void {
  const map = readAll();
  map[entryKey(entry.jobType, entry.entityId)] = {
    ...entry,
    status: entry.status ?? "running",
    timestamp: Date.now(),
  };
  writeAll(map);
}

export function updateActiveJob(
  jobType: ActiveJobType,
  entityId: string | undefined,
  patch: Partial<Pick<ActiveJobEntry, "status" | "meta">>
): void {
  const map = readAll();
  const key = entryKey(jobType, entityId);
  const existing = map[key];
  if (!existing) return;
  map[key] = { ...existing, ...patch };
  writeAll(map);
}

export function clearActiveJob(jobType: ActiveJobType, entityId?: string): void {
  const map = readAll();
  delete map[entryKey(jobType, entityId)];
  writeAll(map);
}

export function getActiveJob(jobType: ActiveJobType, entityId?: string): ActiveJobEntry | null {
  const map = readAll();
  return map[entryKey(jobType, entityId)] ?? null;
}

export function getAllActiveJobs(): ActiveJobEntry[] {
  return Object.values(readAll());
}
