"""Trivial single-node graph for the demo domain. Echoes input to
state, terminates. No external services, no LLM calls.

The whole point is to keep the platform's run-loop machinery
exercised end-to-end without dragging in a real domain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from ai_platform.runtime.worker_log import NullLogger, WorkerLogger
from aiplatform_demo.state import DemoState


@dataclass
class DemoWorkflowDependencies:
    """Per-run inputs for the demo graph."""
    message: str = ""
    logger: WorkerLogger = field(default_factory=NullLogger)


@dataclass
class EchoStep(BaseNode[DemoState, DemoWorkflowDependencies, DemoState]):
    """Read `message` from deps, write its upper-cased form to state, end."""

    stage_label = "Echo"
    stage_description = "Uppercase the input message"

    async def run(
        self, ctx: GraphRunContext[DemoState, DemoWorkflowDependencies]
    ) -> End[DemoState]:
        await ctx.deps.logger.for_stage("EchoStep").info(
            f"echoing message of length {len(ctx.deps.message)}"
        )
        ctx.state.message = ctx.deps.message
        ctx.state.echoed = ctx.deps.message.upper()
        return End(ctx.state)


demo_graph = Graph(
    nodes=(EchoStep,),
    state_type=DemoState,
)


demo_node_registry: dict[str, type] = {
    "EchoStep": EchoStep,
}


def _extract_demo_result(state: DemoState):
    """Build the typed DemoResult from end-state. Returns None when
    state didn't reach the echoed branch (shouldn't happen in normal
    runs but matches the math-qa shape).
    """
    from aiplatform_demo.artifacts import DemoEchoArtifact
    from aiplatform_demo.models import DemoResult

    if state.echoed is None:
        return DemoResult()
    echo = DemoEchoArtifact(original=state.message or "", echoed=state.echoed)
    return DemoResult(echo=echo, artifact_refs=[])
