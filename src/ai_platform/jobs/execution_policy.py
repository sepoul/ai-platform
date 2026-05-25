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


# ---------------------------------------------------------------------------
# Control plane vs. execution plane
#
# A job has two audiences with disjoint needs:
#
#   - the **control plane** (the API process) accepts submissions, renders
#     the workflow, and returns typed results. It needs *schemas* only —
#     never the graph engine — so it can run without any runtime-specific
#     dependency (pydantic_graph, crewai, …).
#   - the **execution plane** (a worker) runs the graph to completion. It
#     needs the graph, nodes, deps factory, and persistence hooks.
#
# `JobControl` and `JobExecution` are those two planes. Today they are
# derived from `JobDefinition` (below) so nothing downstream changes; the
# next step inverts this — domains build the two directly and `JobDefinition`
# is retired. (Named `JobControl`, not `JobSpec`: the platform already has a
# per-run `JobSpec` — job identity — in job_repository.) Topology (edges)
# lives on the execution plane; the API serves it via the generated workflow
# descriptor, not these types. See docs/control_execution_split.md.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobControl:
    """Control-plane view: everything the API needs, nothing from the engine."""
    name: str                                       # key used in API and worker
    label: str                                      # human label (was graph_ref)
    submit_input_type: type[BaseJobInput]           # submit request body schema
    result_type: type[BaseJobResult]                # typed result schema
    gates: list[NodeGate]                           # human-review schemas (node → review_type)
    # Optional: pulls the canonical typed result from the workspace given a
    # JobRecord. The result endpoint prefers this over the in-record
    # `result_payload`. Touches only the shared workspace lib, never the engine.
    fetch_result: Callable[[Any], BaseJobResult] | None = None


@dataclass(frozen=True)
class JobExecution:
    """Execution-plane view: everything a worker needs to run the graph."""
    name: str                                       # key used in API and worker
    graph: Any                                      # pydantic_graph Graph instance
    state_type: type                                # BaseJobState subclass
    start_node_key: str                             # class name of the entry node
    node_registry: dict[str, type]                  # class name → node class (ordered)
    deps_factory: Callable[[dict[str, Any]], Any]   # (deps_payload,) → deps
    extract_result: Callable[[Any], BaseJobResult]  # (state,) → typed result
    policy: ExecutionPolicy                          # executable human-gating
    persistence: PersistencePolicy = field(default_factory=PersistencePolicy)
    edges: list[EdgeSpec] = field(default_factory=list)  # graph topology (for the descriptor)


@dataclass
class JobDefinition:
    """A registered job type as the union of its control + execution planes.

    Transitional: domains still build this flat object, but consumers
    should read through the `.control` and `.execution` views rather than
    the flat fields. Phase 1c inverts ownership — domains build
    `JobControl`/`JobExecution` directly and this class is retired.
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

    @property
    def control(self) -> JobControl:
        """Control-plane view — what the API consumes (see `JobControl`)."""
        return JobControl(
            name=self.name,
            label=self.graph_ref,
            submit_input_type=self.submit_input_type,
            result_type=self.result_type,
            gates=self.policy.gates,
            fetch_result=self.fetch_result,
        )

    @property
    def execution(self) -> JobExecution:
        """Execution-plane view — what a worker consumes (see `JobExecution`)."""
        return JobExecution(
            name=self.name,
            graph=self.graph,
            state_type=self.state_type,
            start_node_key=self.start_node_key,
            node_registry=self.node_registry,
            deps_factory=self.deps_factory,
            extract_result=self.extract_result,
            policy=self.policy,
            persistence=self.persistence,
            edges=self.edges,
        )
