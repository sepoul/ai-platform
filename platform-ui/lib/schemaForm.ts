/**
 * Tiny JSON-Schema renderer for the shape FastAPI/Pydantic emits.
 *
 * Real input_schemas in this platform are simple: a top-level object
 * with `properties` whose entries are `{type: "string"|"integer"|
 * "boolean"}`, `{anyOf: [{type: …}, {type: "null"}]}` (= optional),
 * or `{type: "string", const: "…"}` (a hidden discriminator like
 * `job_type`). That's the surface this module handles. Anything more
 * exotic (nested objects, arrays, refs) gets rendered as a raw JSON
 * textarea — a graceful fallback rather than a crash.
 */

export type Field =
  | { kind: "hidden"; name: string; value: unknown }
  | {
      kind: "string" | "text";
      name: string;
      label: string;
      description?: string;
      required: boolean;
      default?: string;
    }
  | {
      kind: "integer";
      name: string;
      label: string;
      description?: string;
      required: boolean;
      default?: number;
      minimum?: number;
      maximum?: number;
    }
  | {
      kind: "boolean";
      name: string;
      label: string;
      description?: string;
      required: boolean;
      default?: boolean;
    }
  | {
      kind: "json";
      name: string;
      label: string;
      description?: string;
      required: boolean;
      schema: unknown; // raw, shown to the user as a hint
    };

type AnyJsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  required?: string[];
  properties?: Record<string, AnyJsonSchema>;
  const?: unknown;
  default?: unknown;
  anyOf?: AnyJsonSchema[];
  minimum?: number;
  maximum?: number;
};

export function compileSchema(schema: unknown): Field[] {
  const root = (schema as AnyJsonSchema) ?? {};
  const props = root.properties ?? {};
  const required = new Set(root.required ?? []);

  const fields: Field[] = [];
  for (const [name, raw] of Object.entries(props)) {
    fields.push(compileField(name, raw, required.has(name)));
  }
  return fields;
}

function compileField(
  name: string,
  raw: AnyJsonSchema,
  isRequired: boolean,
): Field {
  // Discriminator / fixed value — don't ask the user, just submit it.
  if (raw.const !== undefined) {
    return { kind: "hidden", name, value: raw.const };
  }

  const label = raw.title ?? name;
  const description = raw.description;

  // Optional shape `anyOf: [{type: X}, {type: "null"}]` → unwrap to X
  // but mark not-required.
  const { effective, optionalByAnyOf } = unwrapAnyOf(raw);
  const required = isRequired && !optionalByAnyOf;

  switch (effective.type) {
    case "string": {
      const def = (effective.default ?? undefined) as string | undefined;
      // Heuristic: long-form text → textarea. The description hint
      // is too brittle; just pick textarea for any string field
      // explicitly tagged as containing "text" in its name.
      const kind = /question_text|prompt|body|text/i.test(name) ? "text" : "string";
      return { kind, name, label, description, required, default: def };
    }
    case "integer":
    case "number":
      return {
        kind: "integer",
        name,
        label,
        description,
        required,
        default: effective.default as number | undefined,
        minimum: effective.minimum,
        maximum: effective.maximum,
      };
    case "boolean":
      return {
        kind: "boolean",
        name,
        label,
        description,
        required,
        default: effective.default as boolean | undefined,
      };
    default:
      // Fallback: let the user submit raw JSON, show the schema as a hint.
      return { kind: "json", name, label, description, required, schema: raw };
  }
}

function unwrapAnyOf(raw: AnyJsonSchema): {
  effective: AnyJsonSchema;
  optionalByAnyOf: boolean;
} {
  if (!raw.anyOf || raw.anyOf.length === 0) {
    return { effective: raw, optionalByAnyOf: false };
  }
  const nonNull = raw.anyOf.filter((s) => s.type !== "null");
  const hasNull = raw.anyOf.length !== nonNull.length;
  if (nonNull.length === 1) {
    // Carry the parent's title/description/default — those live on the
    // outer object, not on the unwrapped anyOf branch.
    return {
      effective: {
        ...nonNull[0],
        title: raw.title ?? nonNull[0].title,
        description: raw.description ?? nonNull[0].description,
        default: raw.default ?? nonNull[0].default,
      },
      optionalByAnyOf: hasNull,
    };
  }
  return { effective: raw, optionalByAnyOf: hasNull };
}

/**
 * Build a submission body from form values, stripping empty optional
 * fields (so `created_by: ""` doesn't reach the API as a literal
 * empty string when null was intended) and re-injecting hidden values.
 */
export function buildSubmission(
  fields: Field[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.kind === "hidden") {
      body[f.name] = f.value;
      continue;
    }
    const v = values[f.name];
    if (!f.required && (v === "" || v === undefined || v === null)) continue;
    if (f.kind === "integer") {
      body[f.name] = v === "" || v === null || v === undefined ? null : Number(v);
    } else if (f.kind === "json" && typeof v === "string") {
      try {
        body[f.name] = JSON.parse(v);
      } catch {
        body[f.name] = v; // surface as-is; API will reject with detail
      }
    } else {
      body[f.name] = v;
    }
  }
  return body;
}
