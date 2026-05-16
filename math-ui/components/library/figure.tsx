"use client";

import { useId } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { cn } from "@/lib/utils";

/**
 * Generic textbook-style figure renderer.
 *
 * The agent emits a flat list of *primitive* layout elements
 * (blobs, rectangles, arrows, labels, polygons, dots) at normalized
 * coordinates in `[0, 1] × [0, 1]`. The renderer just draws what
 * it's told — no fixed templates, no per-figure code. The LLM is
 * responsible for picking the layout that explains the concept.
 *
 * Visual style is fixed: black-and-white, hand-drawn-ish blobs,
 * KaTeX-typeset labels via `<foreignObject>`. The LLM controls
 * geometry; the renderer controls polish.
 *
 * Coordinate convention:
 *   x = 0 is left edge, x = 1 is right edge
 *   y = 0 is top edge,  y = 1 is bottom edge
 *   sizes are also normalized (e.g. a blob of size [0.18, 0.20]
 *   is 18% of the canvas wide, 20% tall)
 *
 * Default canvas is 800 × 500 (viewBox); the agent can override
 * with `viewBox: [w, h]` if it wants a different aspect ratio.
 */

// ---------------------------------------------------------------------------
// Spec types
// ---------------------------------------------------------------------------

type Coord = [number, number];

export type FigureElement =
  | BlobElement
  | RectElement
  | CircleElement
  | ArrowElement
  | LineElement
  | LabelElement
  | PolygonElement
  | DotElement;

interface CommonProps {
  label?: string;        // TeX-rendered label
  labelAt?: Coord;       // where to place it; defaults near the shape
}

export interface BlobElement extends CommonProps {
  type: "blob";
  at: Coord;             // center
  size: Coord;           // half-width, half-height
  dashed?: boolean;
  seed?: number;         // jitter seed for reproducible wobble
}

export interface RectElement extends CommonProps {
  type: "rect";
  at: Coord;             // center
  size: Coord;           // total width, height
  grid?: boolean;        // draws a faint dashed grid (signals ℝⁿ patches)
  dashed?: boolean;
}

export interface CircleElement extends CommonProps {
  type: "circle";
  at: Coord;
  radius: number;        // normalized, treated as fraction of min(viewBox)
  dashed?: boolean;
}

export interface ArrowElement {
  type: "arrow";
  from: Coord;
  to: Coord;
  curve?: number;        // perpendicular offset for the curve control point
  label?: string;
  dashed?: boolean;
}

export interface LineElement {
  type: "line";
  from: Coord;
  to: Coord;
  dashed?: boolean;
}

export interface LabelElement {
  type: "label";
  at: Coord;
  text: string;
}

export interface PolygonElement extends CommonProps {
  type: "polygon";
  points: Coord[];
  dashed?: boolean;
  closed?: boolean;      // default true; set false for open chains
}

export interface DotElement extends CommonProps {
  type: "dot";
  at: Coord;
}

export interface FigureSpec {
  title?: string;
  viewBox?: [number, number];   // pixel canvas size; default [800, 500]
  elements: FigureElement[];
}

// ---------------------------------------------------------------------------
// Style
// ---------------------------------------------------------------------------

const STROKE = "currentColor";
const STROKE_WIDTH = 1.4;
const DASH = "5 4";
const DEFAULT_VIEWBOX: [number, number] = [800, 500];

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function Figure({
  spec,
  className,
}: {
  spec: FigureSpec;
  className?: string;
}) {
  const arrowMarkerId = useId();
  const [vw, vh] = spec.viewBox ?? DEFAULT_VIEWBOX;

  return (
    <figure className={cn("flex flex-col gap-2", className)}>
      {spec.title && (
        <figcaption className="text-center text-xs text-muted-foreground">
          {spec.title}
        </figcaption>
      )}
      <svg
        viewBox={`0 0 ${vw} ${vh}`}
        className="w-full text-foreground"
        role="img"
        aria-label={spec.title ?? "figure"}
      >
        <defs>
          <marker
            id={arrowMarkerId}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="8"
            markerHeight="8"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill={STROKE} />
          </marker>
        </defs>
        {(spec.elements ?? []).map((el, i) => (
          <ElementNode
            key={i}
            element={el}
            vw={vw}
            vh={vh}
            arrowMarkerId={arrowMarkerId}
          />
        ))}
      </svg>
    </figure>
  );
}

// ---------------------------------------------------------------------------
// Element dispatcher
// ---------------------------------------------------------------------------

interface NodeProps {
  element: FigureElement;
  vw: number;
  vh: number;
  arrowMarkerId: string;
}

function ElementNode({ element, vw, vh, arrowMarkerId }: NodeProps) {
  switch (element.type) {
    case "blob":
      return <BlobNode el={element} vw={vw} vh={vh} />;
    case "rect":
      return <RectNode el={element} vw={vw} vh={vh} />;
    case "circle":
      return <CircleNode el={element} vw={vw} vh={vh} />;
    case "arrow":
      return <ArrowNode el={element} vw={vw} vh={vh} markerId={arrowMarkerId} />;
    case "line":
      return <LineNode el={element} vw={vw} vh={vh} />;
    case "label":
      return <LabelNode el={element} vw={vw} vh={vh} />;
    case "polygon":
      return <PolygonNode el={element} vw={vw} vh={vh} />;
    case "dot":
      return <DotNode el={element} vw={vw} vh={vh} />;
  }
}

// ---------------------------------------------------------------------------
// Element nodes
// ---------------------------------------------------------------------------

function BlobNode({ el, vw, vh }: { el: BlobElement; vw: number; vh: number }) {
  const [cx, cy] = scale(el.at, vw, vh);
  const [rx, ry] = scaleSize(el.size, vw, vh);
  const path = blobPath(cx, cy, rx, ry, el.seed ?? 1);
  return (
    <g>
      <path
        d={path}
        fill="none"
        stroke={STROKE}
        strokeWidth={STROKE_WIDTH}
        strokeLinejoin="round"
        strokeDasharray={el.dashed ? DASH : undefined}
      />
      {el.label && (
        <MathLabel
          {...resolveLabel(el.label, el.labelAt, [el.at[0], el.at[1] - el.size[1] - 0.04], vw, vh)}
        />
      )}
    </g>
  );
}

function RectNode({ el, vw, vh }: { el: RectElement; vw: number; vh: number }) {
  const [cx, cy] = scale(el.at, vw, vh);
  const w = el.size[0] * vw;
  const h = el.size[1] * vh;
  const x = cx - w / 2;
  const y = cy - h / 2;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        fill="none"
        stroke={STROKE}
        strokeWidth={STROKE_WIDTH}
        strokeDasharray={el.dashed ? DASH : undefined}
      />
      {el.grid &&
        [0.25, 0.5, 0.75].map((t) => (
          <g key={t} opacity={0.4}>
            <line
              x1={x + t * w}
              y1={y}
              x2={x + t * w}
              y2={y + h}
              stroke={STROKE}
              strokeWidth={0.5}
              strokeDasharray="2 4"
            />
            <line
              x1={x}
              y1={y + t * h}
              x2={x + w}
              y2={y + t * h}
              stroke={STROKE}
              strokeWidth={0.5}
              strokeDasharray="2 4"
            />
          </g>
        ))}
      {el.label && (
        <MathLabel
          {...resolveLabel(el.label, el.labelAt, [el.at[0], el.at[1] - el.size[1] / 2 - 0.04], vw, vh)}
        />
      )}
    </g>
  );
}

function CircleNode({ el, vw, vh }: { el: CircleElement; vw: number; vh: number }) {
  const [cx, cy] = scale(el.at, vw, vh);
  const r = el.radius * Math.min(vw, vh);
  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={STROKE}
        strokeWidth={STROKE_WIDTH}
        strokeDasharray={el.dashed ? DASH : undefined}
      />
      {el.label && (
        <MathLabel
          {...resolveLabel(el.label, el.labelAt, [el.at[0], el.at[1] - el.radius - 0.04], vw, vh)}
        />
      )}
    </g>
  );
}

function ArrowNode({
  el,
  vw,
  vh,
  markerId,
}: {
  el: ArrowElement;
  vw: number;
  vh: number;
  markerId: string;
}) {
  const [x1, y1] = scale(el.from, vw, vh);
  const [x2, y2] = scale(el.to, vw, vh);
  const curveAbs = (el.curve ?? 0) * Math.min(vw, vh);
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const cx = mx + nx * curveAbs;
  const cy = my + ny * curveAbs;
  const path = curveAbs
    ? `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`
    : `M ${x1} ${y1} L ${x2} ${y2}`;
  return (
    <g>
      <path
        d={path}
        fill="none"
        stroke={STROKE}
        strokeWidth={STROKE_WIDTH}
        strokeDasharray={el.dashed ? DASH : undefined}
        markerEnd={`url(#${markerId})`}
      />
      {el.label && (
        <MathLabel
          x={cx + nx * (curveAbs >= 0 ? 14 : -14)}
          y={cy + ny * (curveAbs >= 0 ? 14 : -14)}
          text={el.label}
        />
      )}
    </g>
  );
}

function LineNode({ el, vw, vh }: { el: LineElement; vw: number; vh: number }) {
  const [x1, y1] = scale(el.from, vw, vh);
  const [x2, y2] = scale(el.to, vw, vh);
  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={STROKE}
      strokeWidth={STROKE_WIDTH}
      strokeDasharray={el.dashed ? DASH : undefined}
    />
  );
}

function LabelNode({ el, vw, vh }: { el: LabelElement; vw: number; vh: number }) {
  const [x, y] = scale(el.at, vw, vh);
  return <MathLabel x={x} y={y} text={el.text} />;
}

function PolygonNode({ el, vw, vh }: { el: PolygonElement; vw: number; vh: number }) {
  if (!el.points.length) return null;
  const closed = el.closed !== false;
  const points = el.points.map((p) => scale(p, vw, vh));
  const d = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ") + (closed ? " Z" : "");
  return (
    <g>
      <path
        d={d}
        fill="none"
        stroke={STROKE}
        strokeWidth={STROKE_WIDTH}
        strokeLinejoin="round"
        strokeDasharray={el.dashed ? DASH : undefined}
      />
      {el.label && el.labelAt && (
        <MathLabel
          {...resolveLabel(el.label, el.labelAt, el.labelAt, vw, vh)}
        />
      )}
    </g>
  );
}

function DotNode({ el, vw, vh }: { el: DotElement; vw: number; vh: number }) {
  const [cx, cy] = scale(el.at, vw, vh);
  return (
    <g>
      <circle cx={cx} cy={cy} r={3} fill={STROKE} />
      {el.label && (
        <MathLabel
          {...resolveLabel(el.label, el.labelAt, [el.at[0] + 0.015, el.at[1] - 0.025], vw, vh)}
        />
      )}
    </g>
  );
}

// ---------------------------------------------------------------------------
// Label helpers
// ---------------------------------------------------------------------------

interface MathLabelProps {
  x: number;
  y: number;
  text: string;
}

function MathLabel({ x, y, text }: MathLabelProps) {
  const w = 160;
  const h = 32;
  const html = katex.renderToString(text, {
    throwOnError: false,
    strict: "ignore",
    output: "html",
    displayMode: false,
  });
  // `xmlns` would be conventional for SVG-embedded HTML but TS's
  // HTMLAttributes doesn't model it. Browsers infer it inside
  // foreignObject anyway.
  return (
    <foreignObject x={x - w / 2} y={y - h / 2} width={w} height={h}>
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 14,
          color: "currentColor",
          background: "var(--color-card)",
          padding: "0 4px",
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </foreignObject>
  );
}

function resolveLabel(
  text: string,
  labelAt: Coord | undefined,
  fallback: Coord,
  vw: number,
  vh: number
): MathLabelProps {
  const [x, y] = scale(labelAt ?? fallback, vw, vh);
  return { x, y, text };
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function scale(c: Coord, vw: number, vh: number): [number, number] {
  return [c[0] * vw, c[1] * vh];
}

function scaleSize(s: Coord, vw: number, vh: number): [number, number] {
  return [s[0] * vw, s[1] * vh];
}

function blobPath(cx: number, cy: number, rx: number, ry: number, seed: number): string {
  const points = 8;
  const rng = mulberry32(seed * 1000 + 1);
  const ctrl: [number, number][] = [];
  for (let i = 0; i < points; i++) {
    const angle = (i / points) * Math.PI * 2;
    const jitter = 0.85 + rng() * 0.3;
    ctrl.push([cx + rx * jitter * Math.cos(angle), cy + ry * jitter * Math.sin(angle)]);
  }
  const out: string[] = [];
  for (let i = 0; i < ctrl.length; i++) {
    const p0 = ctrl[(i - 1 + ctrl.length) % ctrl.length];
    const p1 = ctrl[i];
    const p2 = ctrl[(i + 1) % ctrl.length];
    const p3 = ctrl[(i + 2) % ctrl.length];
    if (i === 0) out.push(`M ${p1[0].toFixed(2)} ${p1[1].toFixed(2)}`);
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    out.push(
      `C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`
    );
  }
  out.push("Z");
  return out.join(" ");
}

function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
