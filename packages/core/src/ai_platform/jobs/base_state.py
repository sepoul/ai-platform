"""Base state that all job graph states must extend."""
from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class BaseJobState(BaseModel):
    """
    Required base for every graph state used with the generic handler.

    `node_reviews` is the generic review slot: after a gated node runs
    and a human submits a review, the review (serialised as a plain dict)
    is stored here keyed by node class name.  The next nodes — or the
    extract_result callable — read it back out via get_review().

    `artifact_refs` accumulates the IDs of artifacts the persistence
    callback has minted for this job. The platform appends to it as
    callbacks return; domains read it to decide whether more artifacts
    need minting on resume.
    """

    node_reviews: dict[str, dict[str, Any]] = Field(default_factory=dict)
    artifact_refs: list[UUID] = Field(default_factory=list)

    def has_review(self, node_name: str) -> bool:
        return node_name in self.node_reviews

    def get_review(self, node_name: str, review_type: type[T]) -> T | None:
        data = self.node_reviews.get(node_name)
        if data is None:
            return None
        return review_type.model_validate(data)

    def set_review(self, node_name: str, review: BaseModel) -> None:
        self.node_reviews[node_name] = review.model_dump()
