"""Project pydantic models into UI-facing `ParamSpec` rows.

Used by both the workflows router (submit + review params) and the
artifacts router (artifact type fields). Centralized so the
discriminator-skipping rule lives in one place.
"""
from __future__ import annotations

from pydantic import BaseModel

from ai_platform.jobs.workflow_schemas import ParamSpec


def schema_type_label(prop: dict) -> str:
    """Best-effort field type label. Flattens `Optional[X]` (anyOf with
    null) to the non-null branch.
    """
    if "type" in prop:
        return prop["type"]
    if "anyOf" in prop:
        non_null = [
            a.get("type")
            for a in prop["anyOf"]
            if a.get("type") and a.get("type") != "null"
        ]
        if non_null:
            return non_null[0]
    return "object"


def params_from_model(
    model: type[BaseModel],
    *,
    skip_fields: tuple[str, ...] = (),
) -> list[ParamSpec]:
    """Convert a pydantic model's field set into UI-facing ParamSpecs.

    `skip_fields` lets callers drop internal discriminators (e.g.
    `job_type` for input bodies, `artifact_type` for artifact specs).
    """
    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    out: list[ParamSpec] = []
    for name, prop in schema.get("properties", {}).items():
        if name in skip_fields:
            continue
        out.append(
            ParamSpec(
                name=name,
                type=schema_type_label(prop),
                required=name in required,
                description=prop.get("description", "") or "",
            )
        )
    return out
