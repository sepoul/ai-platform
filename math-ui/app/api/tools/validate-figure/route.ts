import { NextResponse } from "next/server";

/**
 * Structural validation for the freeform figure spec.
 *
 * Shape (mirrors what the agent emits — see the figure prompt):
 *
 *   {
 *     "title": "...",                         // optional
 *     "viewBox": [800, 500],                  // optional pixel canvas
 *     "elements": [Element, ...]              // required, ≥ 1
 *   }
 *
 * Each element has a `type` and the props that type requires:
 *
 *   blob    : at, size, dashed?, seed?, label?, labelAt?
 *   rect    : at, size, grid?, dashed?, label?, labelAt?
 *   circle  : at, radius, dashed?, label?, labelAt?
 *   arrow   : from, to, curve?, label?, dashed?
 *   line    : from, to, dashed?
 *   label   : at, text
 *   polygon : points (array of [x,y]), dashed?, closed?, label?, labelAt?
 *   dot     : at, label?, labelAt?
 *
 * Coordinates are normalized in [0, 1] × [0, 1] but we don't
 * enforce that — values just get clipped at render time. We DO
 * enforce that they're numbers.
 *
 * Validation is pure data; no rendering, no eval. Same logic could
 * move to Python without UI dependency.
 *
 * Returns `{ valid: true }` or `{ valid: false, error, path? }`.
 */

const ELEMENT_TYPES = new Set<string>([
  "blob",
  "rect",
  "circle",
  "arrow",
  "line",
  "label",
  "polygon",
  "dot",
]);

interface Body {
  spec?: unknown;
}

interface Fail {
  valid: false;
  error: string;
  path?: string;
}

function fail(error: string, path?: string): NextResponse<Fail> {
  return NextResponse.json({ valid: false, error, path });
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isCoord(v: unknown): v is [number, number] {
  return (
    Array.isArray(v) &&
    v.length === 2 &&
    typeof v[0] === "number" &&
    typeof v[1] === "number"
  );
}

function checkRequiredCoord(
  obj: Record<string, unknown>,
  key: string,
  path: string
): string | null {
  if (!(key in obj)) return `missing \`${key}\` at ${path}`;
  if (!isCoord(obj[key])) return `\`${key}\` must be \`[x, y]\` numbers at ${path}.${key}`;
  return null;
}

function validateElement(el: unknown, path: string): string | null {
  if (!isObject(el)) return `expected an object at ${path}`;
  if (typeof el.type !== "string") return `missing or non-string \`type\` at ${path}`;
  if (!ELEMENT_TYPES.has(el.type)) {
    return `unknown element type "${el.type}" at ${path}.type — known: ${[...ELEMENT_TYPES].join(", ")}`;
  }

  const type = el.type as string;

  // Per-type required fields. Optional booleans/numbers/strings are
  // checked when present.
  switch (type) {
    case "blob":
    case "rect": {
      const e = checkRequiredCoord(el, "at", path) ?? checkRequiredCoord(el, "size", path);
      if (e) return e;
      break;
    }
    case "circle": {
      const e = checkRequiredCoord(el, "at", path);
      if (e) return e;
      if (typeof el.radius !== "number") {
        return `\`radius\` must be a number at ${path}.radius`;
      }
      break;
    }
    case "arrow":
    case "line": {
      const e = checkRequiredCoord(el, "from", path) ?? checkRequiredCoord(el, "to", path);
      if (e) return e;
      break;
    }
    case "label": {
      const e = checkRequiredCoord(el, "at", path);
      if (e) return e;
      if (typeof el.text !== "string") {
        return `\`text\` must be a string at ${path}.text`;
      }
      break;
    }
    case "polygon": {
      if (!Array.isArray(el.points) || el.points.length < 2) {
        return `\`points\` must be an array of ≥2 [x,y] pairs at ${path}.points`;
      }
      for (let i = 0; i < el.points.length; i++) {
        if (!isCoord(el.points[i])) {
          return `\`points[${i}]\` must be [x,y] numbers at ${path}.points[${i}]`;
        }
      }
      break;
    }
    case "dot": {
      const e = checkRequiredCoord(el, "at", path);
      if (e) return e;
      break;
    }
  }

  // Common optional fields with type checks.
  for (const k of ["label", "text"] as const) {
    if (el[k] !== undefined && typeof el[k] !== "string") {
      return `\`${k}\` must be a string at ${path}.${k}`;
    }
  }
  for (const k of ["dashed", "grid", "closed"] as const) {
    if (el[k] !== undefined && typeof el[k] !== "boolean") {
      return `\`${k}\` must be a boolean at ${path}.${k}`;
    }
  }
  for (const k of ["curve", "seed"] as const) {
    if (el[k] !== undefined && typeof el[k] !== "number") {
      return `\`${k}\` must be a number at ${path}.${k}`;
    }
  }
  if (el.labelAt !== undefined && !isCoord(el.labelAt)) {
    return `\`labelAt\` must be [x,y] numbers at ${path}.labelAt`;
  }

  return null;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = await request.json();
  } catch {
    return fail("body is not valid JSON");
  }

  const spec = body.spec;
  if (!isObject(spec)) {
    return fail("`spec` must be an object");
  }

  if (spec.title !== undefined && typeof spec.title !== "string") {
    return fail("`title` must be a string", "title");
  }

  if (spec.viewBox !== undefined) {
    if (
      !Array.isArray(spec.viewBox) ||
      spec.viewBox.length !== 2 ||
      typeof spec.viewBox[0] !== "number" ||
      typeof spec.viewBox[1] !== "number"
    ) {
      return fail("`viewBox` must be `[width, height]` numbers", "viewBox");
    }
  }

  if (!Array.isArray(spec.elements) || spec.elements.length === 0) {
    return fail("`elements` must be a non-empty array", "elements");
  }

  for (let i = 0; i < spec.elements.length; i++) {
    const err = validateElement(spec.elements[i], `elements[${i}]`);
    if (err) return fail(err, `elements[${i}]`);
  }

  return NextResponse.json({ valid: true });
}
