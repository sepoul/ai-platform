"use client";

import {
  useMemo,
  useCallback,
  type CSSProperties,
  type MouseEvent,
} from "react";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  ReactFlowProvider,
  Handle,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Node, Edge, NodeProps } from "reactflow";
import type {
  WorkflowSpecResponse,
  WorkflowStepRuntimeState,
} from "@/lib/platform";
import { layoutWorkflowForReactFlow } from "@/lib/platform";

const END_NODE_ID = "__workflow_end__";

type NodeData = {
  label: string;
  state: WorkflowStepRuntimeState;
  isHuman?: boolean;
  isEnd?: boolean;
  /** Faded when off the active path (upcoming work) */
  dimmed: boolean;
  /** Step list is hovering this stage */
  pulseFromList: boolean;
  clickable?: boolean;
};

function sameId(a: string, b: string | null | undefined): boolean {
  if (!b) return false;
  return a === b || a.toLowerCase() === b.toLowerCase();
}

/** Node is “on the active path” if it’s past, current, or needs attention — not purely upcoming. */
function isOnActivePath(state: WorkflowStepRuntimeState): boolean {
  return state !== "pending";
}

function StatusGlyph({
  state,
  isHuman,
  isEnd,
}: {
  state: WorkflowStepRuntimeState;
  isHuman?: boolean;
  isEnd?: boolean;
}) {
  const box = "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[13px] leading-none";

  if (isEnd) {
    return (
      <span
        className={`${box} ${
          state === "complete"
            ? "bg-[var(--color-success)]/15 text-[var(--color-success)]"
            : state === "error"
              ? "bg-[var(--color-error)]/10 text-[var(--color-error)]"
              : "bg-[var(--color-surface-elevated)] text-[var(--color-text-muted)]"
        }`}
        aria-hidden
      >
        {state === "complete" ? "✓" : "○"}
      </span>
    );
  }

  if (state === "complete") {
    return (
      <span
        className={`${box} bg-[var(--color-success)]/15 text-[var(--color-success)]`}
        aria-hidden
      >
        ✓
      </span>
    );
  }

  if (state === "active") {
    return (
      <span
        className={`${box} bg-[var(--color-primary)]/12 text-[var(--color-primary)]`}
        aria-hidden
      >
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      </span>
    );
  }

  if (state === "human_wait") {
    return (
      <span
        className={`${box} bg-[var(--color-warning)]/15 text-[var(--color-warning)]`}
        title="Your input"
        aria-hidden
      >
        👤
      </span>
    );
  }

  if (state === "error") {
    return (
      <span
        className={`${box} bg-[var(--color-error)]/10 text-[var(--color-error)]`}
        aria-hidden
      >
        !
      </span>
    );
  }

  /* pending / upcoming */
  return (
    <span
      className={`${box} bg-[var(--color-surface-elevated)] text-[var(--color-text-muted)]`}
      aria-hidden
    >
      {isHuman ? "👤" : "○"}
    </span>
  );
}

function WorkflowRfNode({ data }: NodeProps<NodeData>) {
  const { label, state, isHuman, isEnd, dimmed, pulseFromList, clickable } = data;

  const shell =
    dimmed && !pulseFromList
      ? "opacity-[0.42]"
      : "opacity-100";

  const surface =
    state === "complete"
      ? "border-[var(--color-success)]/50 bg-[var(--color-success)]/[0.06]"
      : state === "active"
        ? "border-[var(--color-primary)] bg-[var(--color-primary)]/[0.06] shadow-[0_0_0_1px_var(--color-focus-ring)]"
        : state === "human_wait"
          ? "border-[var(--color-warning)]/60 bg-[var(--color-warning)]/[0.07]"
          : state === "error"
            ? "border-[var(--color-error)]/50 bg-[var(--color-error)]/[0.06]"
            : isHuman && state === "pending"
              ? "border-[var(--color-border)] bg-[var(--color-surface)]"
              : "border-[var(--color-border)] bg-[var(--color-surface)]";

  const ring = pulseFromList ? "ring-2 ring-[var(--color-primary)] ring-offset-1 ring-offset-[var(--color-surface)]" : "";

  return (
    <div
      title={
        clickable && !isEnd ? "Show this step in the list above" : undefined
      }
      className={`min-w-[168px] max-w-[210px] rounded-lg border px-2.5 py-2 text-left text-xs transition-[opacity,box-shadow] duration-200 ${shell} ${surface} ${ring} ${clickable && !isEnd ? "cursor-pointer" : ""}`}
    >
      {!isEnd && (
        <Handle
          type="target"
          position={Position.Left}
          className="!h-2 !w-2 !border !border-[var(--color-border)] !bg-[var(--color-surface)]"
        />
      )}
      <div className="flex items-start gap-2">
        <StatusGlyph state={state} isHuman={isHuman} isEnd={isEnd} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1">
            <span
              className={`font-semibold leading-snug ${
                dimmed && !pulseFromList
                  ? "text-[var(--color-text-muted)]"
                  : "text-[var(--color-text)]"
              }`}
            >
              {isEnd ? "Done" : label}
            </span>
            {isHuman && !isEnd && (
              <span className="rounded bg-[var(--color-warning)]/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-[var(--color-warning)]">
                You
              </span>
            )}
          </div>
        </div>
      </div>
      {!isEnd && (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border !border-[var(--color-border)] !bg-[var(--color-surface)]"
        />
      )}
    </div>
  );
}

const nodeTypes = { workflowStep: WorkflowRfNode };

function endNodeState(
  status: string | null | undefined
): WorkflowStepRuntimeState {
  const u = (status ?? "").toUpperCase();
  if (u === "SUCCEEDED" || u === "SUCCESS") return "complete";
  if (u === "FAILED" || u === "CANCELLED") return "error";
  return "pending";
}

function resolveEdgeStyle(
  sourceState: WorkflowStepRuntimeState,
  targetState: WorkflowStepRuntimeState
): { opacity: number; stroke: string; strokeWidth: number; animated?: boolean } {
  const srcOn = isOnActivePath(sourceState);
  const tgtOn = isOnActivePath(targetState);
  const bothPending = sourceState === "pending" && targetState === "pending";
  const forward = sourceState === "complete" && targetState === "pending";

  if (bothPending) {
    return {
      opacity: 0.35,
      stroke: "var(--color-border)",
      strokeWidth: 1.2,
    };
  }
  if (forward) {
    return {
      opacity: 1,
      stroke: "var(--color-primary)",
      strokeWidth: 2,
      animated: true,
    };
  }
  if (srcOn && tgtOn) {
    return {
      opacity: 1,
      stroke: "var(--color-success)",
      strokeWidth: 2,
    };
  }
  if (srcOn || tgtOn) {
    return {
      opacity: 0.75,
      stroke: "var(--color-primary-muted)",
      strokeWidth: 1.6,
    };
  }
  return {
    opacity: 0.45,
    stroke: "var(--color-border)",
    strokeWidth: 1.2,
  };
}

export interface WorkflowGraphViewProps {
  spec: WorkflowSpecResponse;
  stateByStageId: Map<string, WorkflowStepRuntimeState>;
  jobStatus: string | null;
  /** Step list hover — highlights matching node */
  highlightedStageId?: string | null;
  /** Click node — parent scrolls step list */
  onNodeSelect?: (stageId: string) => void;
  className?: string;
  style?: CSSProperties;
}

export function WorkflowGraphView({
  spec,
  stateByStageId,
  jobStatus,
  highlightedStageId,
  onNodeSelect,
  className,
  style,
}: WorkflowGraphViewProps) {
  const { nodes: layoutNodes, endX, endY } = useMemo(
    () => layoutWorkflowForReactFlow(spec),
    [spec]
  );

  const getState = useCallback(
    (id: string): WorkflowStepRuntimeState => {
      const direct = stateByStageId.get(id);
      if (direct !== undefined) return direct;
      for (const [k, v] of stateByStageId) {
        if (k.toLowerCase() === id.toLowerCase()) return v;
      }
      return "pending";
    },
    [stateByStageId]
  );

  const { nodes, edges } = useMemo(() => {
    const rfNodes: Node<NodeData>[] = layoutNodes.map((n) => {
      const st = getState(n.id);
      const listHover = sameId(n.id, highlightedStageId);
      const dimmed = st === "pending" && !listHover;

      return {
        id: n.id,
        type: "workflowStep",
        position: { x: n.x, y: n.y },
        data: {
          label: spec.stages.find((s) => s.id === n.id)?.label ?? n.id,
          state: st,
          isHuman: spec.stages.find((s) => s.id === n.id)?.is_human_step,
          dimmed,
          pulseFromList: listHover,
          clickable: !!onNodeSelect,
        },
      };
    });

    const endSt = endNodeState(jobStatus);

    rfNodes.push({
      id: END_NODE_ID,
      type: "workflowStep",
      position: { x: endX, y: endY },
      data: {
        label: "Done",
        state: endSt,
        isEnd: true,
        dimmed: endSt === "pending",
        pulseFromList: false,
      },
    });

    const rfEdges: Edge[] = spec.edges.map((e, i) => {
      const tgtId = e.target === "End" ? END_NODE_ID : e.target;
      const srcState = getState(e.source);
      const tgtState =
        tgtId === END_NODE_ID ? endNodeState(jobStatus) : getState(tgtId);
      const es = resolveEdgeStyle(srcState, tgtState);

      return {
        id: `e-${i}-${e.source}-${e.target}`,
        source: e.source,
        target: tgtId,
        label: e.label ?? undefined,
        labelStyle: {
          fontSize: 10,
          fill: "var(--color-text-muted)",
          opacity: es.opacity,
        },
        style: {
          stroke: es.stroke,
          strokeWidth: es.strokeWidth,
          opacity: es.opacity,
        },
        animated: es.animated,
        type: "smoothstep",
      };
    });

    return { nodes: rfNodes, edges: rfEdges };
  }, [
    spec,
    layoutNodes,
    endX,
    endY,
    stateByStageId,
    jobStatus,
    highlightedStageId,
    getState,
    onNodeSelect,
  ]);

  const onNodeClick = useCallback(
    (_: MouseEvent, node: Node<NodeData>) => {
      if (node.id === END_NODE_ID) return;
      onNodeSelect?.(node.id);
    },
    [onNodeSelect]
  );

  return (
    <div
      className={`h-[min(420px,55vh)] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-elevated)]/40 ${className ?? ""}`}
      style={style}
      role="img"
      aria-label="Process overview map"
    >
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeSelect ? onNodeClick : undefined}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.4}
          maxZoom={1.4}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
