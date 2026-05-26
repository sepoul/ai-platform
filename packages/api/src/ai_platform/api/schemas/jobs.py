from __future__ import annotations

import operator
from datetime import date, datetime
from functools import reduce
from typing import Annotated, Optional

from pydantic import BaseModel, Field, RootModel, create_model

from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult


class JobListParams(BaseModel):
    """Typed query parameters for GET /jobs."""
    status: Optional[str] = None
    job_type: Optional[str] = None
    created_after: Optional[date] = None
    created_before: Optional[date] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RunSubmitResponse(BaseModel):
    job_id: str
    status: str


# ---------------------------------------------------------------------------
# Discriminated-union response model builders
#
# The platform exposes results as a Pydantic discriminated union over
# `job_type`. The set of variants is the `result_type` of every registered
# `JobControl`, so it must be assembled at composition time (after the
# domain has registered its jobs).
# ---------------------------------------------------------------------------


def _build_result_field(result_types: list[type[BaseJobResult]]):
    """Build the `Optional[<discriminated union>]` annotation."""
    if not result_types:
        return Optional[BaseJobResult]
    if len(result_types) == 1:
        # A discriminated Union of a single member collapses to that member;
        # the discriminator is still present on the model so TS clients can
        # narrow on it.
        return Optional[result_types[0]]
    union = reduce(operator.or_, result_types)
    return Optional[Annotated[union, Field(discriminator="job_type")]]


def build_job_result_response_model(
    result_types: list[type[BaseJobResult]],
) -> type[BaseModel]:
    field = _build_result_field(result_types)
    return create_model(
        "JobResultResponse",
        job_id=(str, ...),
        result=(field, None),
    )


def build_run_submit_request_model(
    input_types: list[type[BaseJobInput]],
) -> type[BaseModel]:
    """Build the typed request body for POST /jobs/runs/submit.

    - 1 input registered  → that input type directly.
    - N inputs registered → a `RootModel` over the discriminated union,
      keyed on `job_type`. The wire format stays a flat object; FastAPI
      treats `RootModel[X]` as `X` for body parsing.
    """
    if len(input_types) == 1:
        return input_types[0]
    union = reduce(operator.or_, input_types)
    return RootModel[Annotated[union, Field(discriminator="job_type")]]


def build_review_request_model(
    review_types: list[type[BaseModel]],
) -> type[BaseModel]:
    """Build the typed request body for POST /jobs/{job_id}/review.

    The body is the union of every registered `NodeGate.review_type`
    across all jobs. There is no in-body discriminator (gates are looked
    up via the job's checkpoint), so the union is untagged — pydantic
    matches on field shape. With one gate type, it collapses to that type.
    """
    # Deduplicate while preserving order so OpenAPI is stable.
    seen: dict[type[BaseModel], None] = {}
    for t in review_types:
        seen.setdefault(t, None)
    unique = list(seen)

    if not unique:
        # No gates registered → endpoint is wired but unreachable. Return a
        # placeholder so FastAPI can still build the route schema.
        return create_model("ReviewRequest")
    if len(unique) == 1:
        return unique[0]
    union = reduce(operator.or_, unique)
    return RootModel[union]


def build_job_status_response_model(
    result_types: list[type[BaseJobResult]],
) -> type[BaseModel]:
    field = _build_result_field(result_types)
    return create_model(
        "JobStatusResponse",
        job_id=(str, ...),
        job_type=(str, ...),
        status=(str, ...),
        created_at=(datetime, ...),
        stage=(Optional[str], None),
        percent=(Optional[float], None),
        message=(Optional[str], None),
        waiting_for=(Optional[str], None),
        error_message=(Optional[str], None),
        result=(field, None),
    )
