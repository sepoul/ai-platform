import type {
  EdgeResponse,
  WorkflowSpecResponse,
  StageResponse,
  WorkflowStepRuntimeState,
  ResolvedWorkflowStep,
} from "./workflow-types";

const END_TARGETS = new Set(["End", "__workflow_end__"]);

function stageById(stages: StageResponse[]): Map<string, StageResponse> {
  return new Map(stages.map((s) => [s.id, s]));
}

/** Roots: stage nodes with no incoming edge from another stage (targets may be End). */
function findRoots(stageIds: Set<string>, edges: EdgeResponse[]): string[] {
  const incoming = new Set<string>();
  for (const e of edges) {
    if (END_TARGETS.has(e.target)) continue;
    if (stageIds.has(e.source) && stageIds.has(e.target)) {
      incoming.add(e.target);
    }
  }
  return [...stageIds].filter((id) => !incoming.has(id));
}

/** Adjacency among stage ids only (skips End). */
function buildAdjacency(
  stageIds: Set<string>,
  edges: EdgeResponse[]
): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  for (const id of stageIds) adj.set(id, []);
  for (const e of edges) {
    if (!stageIds.has(e.source)) continue;
    if (END_TARGETS.has(e.target)) continue;
    if (stageIds.has(e.target)) {
      adj.get(e.source)!.push(e.target);
    }
  }
  return adj;
}

/**
 * Deterministic topological order; falls back to declaration order if the graph is cyclic
 * or otherwise invalid.
 */
export function topologicalStageOrder(
  stages: StageResponse[],
  edges: EdgeResponse[]
): string[] {
  const stageIds = new Set(stages.map((s) => s.id));
  const inDegree = new Map<string, number>();
  for (const id of stageIds) inDegree.set(id, 0);

  const adj = buildAdjacency(stageIds, edges);
  for (const tos of adj.values()) {
    for (const t of tos) {
      inDegree.set(t, (inDegree.get(t) ?? 0) + 1);
    }
  }

  const roots = [...stageIds].filter((id) => inDegree.get(id) === 0).sort();
  const out: string[] = [];
  const q = [...roots];

  while (q.length) {
    const id = q.shift()!;
    out.push(id);
    for (const nxt of adj.get(id) ?? []) {
      const next = inDegree.get(nxt)! - 1;
      inDegree.set(nxt, next);
      if (next === 0) {
        q.push(nxt);
        q.sort();
      }
    }
  }

  if (out.length !== stageIds.size) {
    return stages.map((s) => s.id);
  }
  return out;
}

function normalizeStageId(raw: string | null | undefined): string | null {
  if (raw == null || !String(raw).trim()) return null;
  return String(raw).trim();
}

function isHumanWaiting(
  status: string,
  stage: StageResponse | undefined
): boolean {
  // The backend's ExecutionPolicy is now surfaced on the spec — every
  // gated stage carries `is_human_step=true`. No need for string
  // heuristics on `waiting_for` anymore.
  if (status.toUpperCase() !== "WAITING_INPUT") return false;
  return !!stage?.is_human_step;
}

/**
 * Maps live job telemetry to per-step UI state for the stepper and graph.
 */
export function resolveWorkflowStepStates(
  spec: WorkflowSpecResponse,
  input: {
    status: string | null;
    stage: string | null;
    errorMessage?: string | null;
  }
): {
  orderedSteps: ResolvedWorkflowStep[];
  currentStageId: string | null;
} {
  const order = topologicalStageOrder(spec.stages, spec.edges);
  const byId = stageById(spec.stages);
  const status = (input.status ?? "").toUpperCase();
  const current = normalizeStageId(input.stage);
  const orderIndex = new Map(order.map((id, i) => [id, i]));

  const indexOfCurrent = (id: string | null): number => {
    if (!id) return -1;
    const direct = orderIndex.get(id);
    if (direct !== undefined) return direct;
    const lower = id.toLowerCase();
    const fuzzy = order.findIndex((x) => x.toLowerCase() === lower);
    return fuzzy;
  };

  const sameStage = (a: string, b: string | null): boolean => {
    if (!b) return false;
    return a === b || a.toLowerCase() === b.toLowerCase();
  };

  const stateFor = (id: string): WorkflowStepRuntimeState => {
    const st = byId.get(id);
    const idx = orderIndex.get(id) ?? 0;
    const curIdx = current ? indexOfCurrent(current) : -1;

    if (status === "SUCCEEDED" || status === "SUCCESS") {
      return "complete";
    }
    if (status === "FAILED" || status === "CANCELLED") {
      if (current && sameStage(id, current)) return "error";
      if (curIdx >= 0 && idx < curIdx) return "complete";
      return "pending";
    }

    if (!current) {
      if (status === "PENDING" || status === "RUNNING") return "pending";
      return "pending";
    }

    if (sameStage(id, current)) {
      if (isHumanWaiting(input.status ?? "", st)) {
        return "human_wait";
      }
      return "active";
    }

    if (idx < curIdx) return "complete";
    return "pending";
  };

  const orderedSteps: ResolvedWorkflowStep[] = order.map((id, stepOrd) => ({
    stage: byId.get(id)!,
    state: stateFor(id),
    orderIndex: stepOrd,
  }));

  return {
    orderedSteps,
    currentStageId: current,
  };
}

/** Layer index per stage for left-to-right layout (0 = start). */
export function workflowLayers(
  stages: StageResponse[],
  edges: EdgeResponse[]
): Map<string, number> {
  const stageIds = new Set(stages.map((s) => s.id));
  const adj = buildAdjacency(stageIds, edges);
  const roots = findRoots(stageIds, edges).sort();
  const depth = new Map<string, number>();

  /** DFS with cycle guard: specs may include feedback edges (e.g. human step → earlier stage). */
  const visit = (id: string, d: number, onStack: Set<string>) => {
    if (onStack.has(id)) return;
    const prev = depth.get(id);
    if (prev !== undefined && prev >= d) return;
    depth.set(id, d);
    onStack.add(id);
    for (const nxt of adj.get(id) ?? []) {
      visit(nxt, d + 1, onStack);
    }
    onStack.delete(id);
  };

  for (const r of roots) visit(r, 0, new Set());

  let maxD = 0;
  for (const id of stageIds) {
    if (!depth.has(id)) {
      depth.set(id, 0);
    }
    maxD = Math.max(maxD, depth.get(id)!);
  }

  return depth;
}

const NODE_W = 200;
const NODE_H = 72;
const GAP_X = 56;
const GAP_Y = 24;

export interface LayoutedWorkflowNode {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Simple layered layout for React Flow: groups nodes by depth, stacks vertically within a layer.
 */
export function layoutWorkflowForReactFlow(
  spec: WorkflowSpecResponse
): { nodes: LayoutedWorkflowNode[]; endX: number; endY: number } {
  const stages = spec.stages;
  const edges = spec.edges;
  const layers = workflowLayers(stages, edges);
  const byLayer = new Map<number, string[]>();
  for (const s of stages) {
    const L = layers.get(s.id) ?? 0;
    if (!byLayer.has(L)) byLayer.set(L, []);
    byLayer.get(L)!.push(s.id);
  }
  for (const [, ids] of byLayer) {
    ids.sort(
      (a, b) =>
        (stages.find((x) => x.id === a)?.label ?? a).localeCompare(
          stages.find((x) => x.id === b)?.label ?? b
        )
    );
  }

  const nodes: LayoutedWorkflowNode[] = [];
  const maxLayer = Math.max(0, ...[...byLayer.keys()]);

  for (let L = 0; L <= maxLayer; L++) {
    const ids = byLayer.get(L) ?? [];
    const colX = L * (NODE_W + GAP_X);
    ids.forEach((id, row) => {
      nodes.push({
        id,
        x: colX,
        y: row * (NODE_H + GAP_Y),
        width: NODE_W,
        height: NODE_H,
      });
    });
  }

  const maxY = nodes.length
    ? Math.max(...nodes.map((n) => n.y + n.height))
    : NODE_H;
  const endX = (maxLayer + 1) * (NODE_W + GAP_X);
  const endY = Math.max(0, maxY / 2 - NODE_H / 2);

  return { nodes, endX, endY };
}
