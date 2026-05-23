"""Execution policy — human-gate and persistence declarations separate from graph logic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from ai_platform.jobs.input import BaseJobInput
from ai_platform.jobs.result import BaseJobResult

ReviewT = TypeVar("ReviewT", bound=BaseModel)


@dataclass
class NodeGate(Generic[ReviewT]):
    """
    Declares that after `node_name` runs, a human review of type `ReviewT`
    is required before the job continues.  The handler fires this gate
    by checking the node that *just ran*, not the one about to run.
    """
    node_name: str                       # class name of the gated node
    review_type: type[ReviewT]           # pydantic model for the review — also the API request body


@dataclass
class ExecutionPolicy:
    gates: list[NodeGate] = field(default_factory=list)

    def gate_for(self, node_name: str) -> NodeGate | None:
        return next((g for g in self.gates if g.node_name == node_name), None)

    def validate(self, graph: Any) -> None:
        """Raise ValueError if any gate references a node not in the graph."""
        node_names = set(graph.node_defs.keys())
        for gate in self.gates:
            if gate.node_name not in node_names:
                raise ValueError(
                    f"Policy gate '{gate.node_name}' not in graph nodes: {node_names}"
                )


PersistCallback = Callable[[str, Any], list[UUID]]


@dataclass
class PersistencePolicy:
    """Declares when domain artifacts are persisted.

    Callbacks are `(job_id, state) -> list[UUID]`: each call mints zero
    or more artifacts in the workspace and returns their IDs. The
    platform appends those IDs to `state.artifact_refs` on the
    `JobRecord`. Any domain client must be closed over by the domain
    when building the `JobDefinition`.
    """
    on_complete: PersistCallback | None = None   # job succeeded
    on_pause: PersistCallback | None = None      # job waiting for human review


@dataclass
class EdgeSpec:
    """Topology edge between two graph nodes — domain declares, platform renders."""
    source: str
    target: str
    label: str | None = None


@dataclass
class JobDefinition:
    """Single source of truth for a registered job type.

    Fully self-contained: the executor calls deps_factory and persistence
    callbacks without knowing anything about domain clients.
    """
    name: str                         # key used in API and worker ("math_qa")
    graph_ref: str                    # human label ("math_qa_graph")
    graph: Any                        # pydantic_graph Graph instance
    state_type: type                  # BaseJobState subclass
    start_node_key: str               # class name of the entry node
    node_registry: dict[str, type]    # class name → node class (ordered; first = start)
    deps_factory: Callable[[dict[str, Any]], Any]   # (deps_payload,) → deps
    policy: ExecutionPolicy
    result_type: type[BaseJobResult]                            # typed result schema for this job
    extract_result: Callable[[Any], BaseJobResult]              # (state,) → typed result
    submit_input_type: type[BaseJobInput]                       # typed schema for the submit request body
    persistence: PersistencePolicy = field(default_factory=PersistencePolicy)
    edges: list[EdgeSpec] = field(default_factory=list)
    # Optional: pulls the canonical typed result from the workspace given a
    # JobRecord. When defined, the result endpoint prefers this over the
    # in-record `result_payload`, which then acts as a cheap status preview.
    # Domains close over their workspace client when building the callback.
    fetch_result: Callable[[Any], BaseJobResult] | None = None
    # Which worker runtime executes this job. A worker only claims jobs
    # whose runtime matches its WORKER_RUNTIME; jobs for other runtimes
    # are left for the pool that can run them. See ai_platform.jobs.runtimes.
    # Domains needing a conflicting dependency stack (e.g. crewai vs the
    # default logfire stack) set this to route onto an isolated pool.
    runtime: str = "default"
