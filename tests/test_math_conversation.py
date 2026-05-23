"""Tests for the math_conversation domain skeleton (T1), artifact schema
(T2), and the crew chat-event emitters (T4).

All of this is CrewAI-free and needs no network — the crew internals
(T5/T6) slot into `RunCrewStep` later without touching these contracts.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_platform.jobs.artifact_service import ArtifactService
from ai_platform.workspace.storage.structured.artifact_repository import LocalArtifactRepository
from ai_platform.workspace.storage.structured.local import LocalRepositoryConfig

from mathai.math_conversation.artifacts import (
    MATH_CONVERSATION_ARTIFACTS,
    ConversationTurn,
    MathConversationArtifact,
    ToolCallRecord,
)
from mathai.math_conversation.crew.callbacks import (
    CREW_CHAT_SOURCE,
    CrewChatEmitter,
    CrewChatEvent,
    friendly_tool_name,
)
from mathai.math_conversation.models import MathConversationInput
from mathai.math_conversation.state import MathConversationState
from mathai.math_conversation.workflow import (
    MathConversationDeps,
    SeedStep,
    build_math_conversation_job_definition,
    math_conversation_graph,
)


# ---------------------------------------------------------------------------
# T1 — input validator (exactly-one source)
# ---------------------------------------------------------------------------

def test_input_rejects_both_sources():
    with pytest.raises(ValidationError, match="exactly one"):
        MathConversationInput(source_job_id=uuid4(), question_text="hi")


def test_input_rejects_neither_source():
    with pytest.raises(ValidationError, match="exactly one"):
        MathConversationInput()


def test_input_accepts_question_text():
    inp = MathConversationInput(question_text="What is a group?")
    assert inp.question_text == "What is a group?"
    assert inp.job_type == "math_conversation"
    assert inp.max_turns == 12


def test_input_accepts_source_job_id():
    jid = uuid4()
    inp = MathConversationInput(source_job_id=jid)
    assert inp.source_job_id == jid


def test_input_max_turns_bounds():
    with pytest.raises(ValidationError):
        MathConversationInput(question_text="x", max_turns=0)
    with pytest.raises(ValidationError):
        MathConversationInput(question_text="x", max_turns=31)


# ---------------------------------------------------------------------------
# T1 — graph runs to End for both input forms
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_graph_runs_to_end_with_question_text():
    state = MathConversationState()
    deps = MathConversationDeps(question_text="What is a manifold?", max_turns=5)
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.seed_question == "What is a manifold?"
    assert state.max_turns == 5
    assert state.stop_reason == "max_turns"


@pytest.mark.anyio
async def test_graph_runs_to_end_with_source_job_id():
    jid = uuid4()
    state = MathConversationState()
    deps = MathConversationDeps(source_job_id=jid)
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.source_job_id == jid
    assert state.stop_reason == "max_turns"


@pytest.mark.anyio
async def test_conclude_flag_sets_stop_reason():
    state = MathConversationState(concluded=True)
    deps = MathConversationDeps(question_text="x")
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.stop_reason == "concluded"


# ---------------------------------------------------------------------------
# T1 — job definition: deps_factory, persist, fetch_result
# ---------------------------------------------------------------------------

class _Workspace:
    def __init__(self, store):
        self.artifact_store = store


@pytest.fixture
def job_def(tmp_path: Path):
    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    store = ArtifactService(repo, registry=MATH_CONVERSATION_ARTIFACTS)
    return build_math_conversation_job_definition(_Workspace(store)), store


def test_deps_factory_parses_payload(job_def):
    jd, _ = job_def
    jid = uuid4()
    deps = jd.deps_factory({"source_job_id": str(jid), "max_turns": 7})
    assert deps.source_job_id == jid
    assert deps.max_turns == 7
    assert deps.question_text is None


def test_persist_mints_conversation_artifact(job_def):
    jd, store = job_def
    state = MathConversationState(
        seed_question="What is a group?",
        turns=[ConversationTurn(turn_index=0, agent_role="Algebraist", agent_persona="algebraist", content="...")],
        cost_so_far=0.05,
        stop_reason="concluded",
    )
    ids = jd.persistence.on_complete("job-1", state)
    assert len(ids) == 1
    art = store.get(ids[0])
    assert isinstance(art, MathConversationArtifact)
    assert art.seed_question == "What is a group?"
    assert art.stop_reason == "concluded"
    assert art.total_cost_usd == 0.05
    assert len(art.turns) == 1

    # Idempotent: a second call with refs populated mints nothing.
    state.artifact_refs = list(ids)
    assert jd.persistence.on_complete("job-1", state) == []


def test_fetch_result_hydrates_conversation(job_def):
    jd, store = job_def
    art = MathConversationArtifact(seed_question="2+2?", stop_reason="max_turns")
    store.put(art)

    from unittest.mock import MagicMock
    record = MagicMock()
    record.state.resume_token = None
    record.state.result_payload = {"artifact_refs": [str(art.artifact_id)]}

    result = jd.fetch_result(record)
    assert result.conversation is not None
    assert result.conversation.seed_question == "2+2?"
    assert result.artifact_refs == [art.artifact_id]


# ---------------------------------------------------------------------------
# T2 — artifact / turn round-trip
# ---------------------------------------------------------------------------

def test_artifact_roundtrip_with_inline_latex_and_figure():
    art = MathConversationArtifact(
        seed_question="Explain a chart on a manifold.",
        turns=[
            ConversationTurn(
                turn_index=0, agent_role="Visualist", agent_persona="visualist",
                content="Picture a sphere with two overlapping patches.",
                figure={"template": "manifold-chart", "objects": []},
                tool_calls=[ToolCallRecord(tool_name="validate_figure", arguments={"spec": {}})],
                cost_usd=0.02,
            ),
            ConversationTurn(
                turn_index=1, agent_role="Algebraist", agent_persona="algebraist",
                content="Formally, a chart is a homeomorphism.", latex="\\phi: U \\to \\mathbb{R}^n",
                cost_usd=0.03,
            ),
        ],
        total_cost_usd=0.05,
        stop_reason="concluded",
    )
    back = MathConversationArtifact.model_validate_json(art.model_dump_json())
    assert back.turns[0].figure["template"] == "manifold-chart"
    assert back.turns[0].tool_calls[0].tool_name == "validate_figure"
    assert back.turns[1].latex == "\\phi: U \\to \\mathbb{R}^n"
    assert back.total_cost_usd == 0.05
    assert back.artifact_type == "math_conversation"


def test_artifact_registry_key():
    assert MATH_CONVERSATION_ARTIFACTS == {"math_conversation": MathConversationArtifact}


# ---------------------------------------------------------------------------
# T4 — crew chat emitters
# ---------------------------------------------------------------------------

class _FakeLogger:
    """Captures emitted messages so we can assert the event sequence."""

    def __init__(self):
        self.job_id = "fake"
        self.stage = None
        self.source = "test"
        self.messages: list[str] = []

    async def emit(self, message: str, *, level: str = "info") -> None:
        self.messages.append(message)

    def for_stage(self, stage: str):
        return self


def _events(logger: _FakeLogger) -> list[CrewChatEvent]:
    return [CrewChatEvent.model_validate_json(m) for m in logger.messages]


@pytest.mark.anyio
async def test_emitter_fires_expected_sequence():
    logger = _FakeLogger()
    em = CrewChatEmitter(logger, turns_budget=3, start=0.0)

    await em.emit_signed_in("Algebraist", "Algebraist")
    await em.emit_signed_in("Visualist", "Visualist")
    await em.emit_signed_in("Synthesist", "Synthesist")
    await em.emit_typing("Algebraist", "Algebraist")
    await em.emit_message("Algebraist", "Algebraist", 0, "A group is a set with...", cost_usd=0.01)
    await em.emit_typing("Visualist", "Visualist")
    await em.emit_message("Visualist", "Visualist", 1, "Picture symmetries...", latex="D_4")
    await em.emit_status(turns_used=2, cost_usd=0.02)
    await em.emit_concluded("Synthesist", "Synthesist", content="We've covered it.")
    await em.emit_signed_out("Synthesist", "Synthesist")

    events = _events(logger)
    assert [e.event for e in events] == [
        "signed_in", "signed_in", "signed_in",
        "is_typing", "message", "is_typing", "message",
        "status", "concluded", "signed_out",
    ]
    # signed_in carries the budget; message carries content/turn_index.
    assert events[0].turns_budget == 3
    msg = events[4]
    assert msg.turn_index == 0 and msg.content.startswith("A group") and msg.cost_usd == 0.01
    assert events[6].latex == "D_4"
    status = events[7]
    assert status.turns_used == 2 and status.turns_budget == 3 and status.cost_usd == 0.02


@pytest.mark.anyio
async def test_emitter_tool_events_use_raw_name():
    logger = _FakeLogger()
    em = CrewChatEmitter(logger, start=0.0)
    await em.emit_tool_call("Algebraist", "Algebraist", "validate_latex")
    await em.emit_tool_result("Algebraist", "Algebraist", "validate_latex")
    events = _events(logger)
    assert [e.event for e in events] == ["tool_call", "tool_result"]
    assert all(e.tool_name == "validate_latex" for e in events)


def test_friendly_tool_name_map():
    assert friendly_tool_name("validate_latex") == "checking the LaTeX"
    assert friendly_tool_name("validate_figure") == "sketching the figure"
    assert friendly_tool_name("conclude") == "wrapping up"
    assert friendly_tool_name("unknown_tool") == "unknown_tool"


@pytest.mark.anyio
async def test_emitter_emits_valid_json_objects_with_event_key():
    """The UI live parser detects crew events by JSON-parsing each log
    line and checking for an `event` key. Every emitted message must
    satisfy that."""
    logger = _FakeLogger()
    em = CrewChatEmitter(logger, start=0.0)
    await em.emit_signed_in("Algebraist", "Algebraist")
    payload = json.loads(logger.messages[0])
    assert payload["event"] == "signed_in"
    assert payload["display_name"] == "Algebraist"


def test_crew_chat_logger_retags_source():
    from ai_platform.runtime.worker_log import WorkerLogger
    from mathai.math_conversation.crew.callbacks import crew_chat_logger
    base = WorkerLogger(job_id="abc")
    tagged = crew_chat_logger(base)
    assert tagged.source == CREW_CHAT_SOURCE
    assert tagged.job_id == "abc"


# ---------------------------------------------------------------------------
# T3 — persona / skill registry
# ---------------------------------------------------------------------------

def test_load_persona_algebraist():
    from mathai.math_conversation.registry import load_persona
    persona = load_persona("algebraist")
    assert persona.role == "Algebraist"
    assert persona.display_name == "🧮 Algebraist"
    assert persona.model == "gpt-4o"
    assert persona.skills == ["symbolic-manipulation", "proof-checking"]
    assert persona.goal
    assert "rigor" in persona.body.lower()


def test_load_skill_symbolic_manipulation():
    from mathai.math_conversation.registry import load_skill
    skill = load_skill("symbolic-manipulation")
    assert skill.description.startswith("Algebraic manipulation")
    assert skill.tool_allowlist == ["validate_latex"]
    assert skill.body  # one-line stub body


def test_all_three_personae_load_with_resolvable_skills():
    from mathai.math_conversation.registry import load_persona, load_skill
    for name in ("algebraist", "visualist", "synthesist"):
        persona = load_persona(name)
        assert 1 <= len(persona.skills) <= 2
        # Every declared skill resolves to a real skill file.
        for skill_name in persona.skills:
            skill = load_skill(skill_name)
            assert skill.name == skill_name
            assert skill.tool_allowlist  # stubs still declare a tool allowlist


def test_parse_frontmatter_handles_no_frontmatter():
    from ai_platform.ai.prompts.registry import parse_frontmatter
    meta, body = parse_frontmatter("just a body, no front-matter")
    assert meta == {}
    assert body == "just a body, no front-matter"


def test_parse_persona_rejects_wrong_kind():
    from mathai.math_conversation.registry import parse_persona
    with pytest.raises(ValueError, match="kind: persona"):
        parse_persona("---\nkind: skill\nrole: X\n---\nbody", "x")


def test_prompt_definitions_include_personae_and_skills():
    from ai_platform.ai.prompts.registry import PROMPT_DEFINITIONS
    names = {p.name: p for p in PROMPT_DEFINITIONS}
    assert "math_conversation.persona.algebraist" in names
    assert "math_conversation.skill.symbolic-manipulation" in names
    persona_entry = names["math_conversation.persona.algebraist"]
    assert persona_entry.kind == "persona"
    # The stored instructions carry the full Markdown incl. front-matter,
    # so a /prompts round-trip re-parses to the same spec.
    from mathai.math_conversation.registry import parse_persona
    reparsed = parse_persona(persona_entry.instructions, "algebraist")
    assert reparsed.skills == ["symbolic-manipulation", "proof-checking"]
    assert reparsed.model == "gpt-4o"


def test_discovered_skills_have_skill_kind():
    from ai_platform.ai.prompts.registry import PROMPT_DEFINITIONS
    skills = [p for p in PROMPT_DEFINITIONS if p.name.startswith("math_conversation.skill.")]
    assert len(skills) >= 5
    assert all(p.kind == "skill" for p in skills)


# ---------------------------------------------------------------------------
# T7 — submission through the real platform job-runs endpoint
#
# The generic router builds its request body from the discriminated union
# of every registered submit_input_type, so registering the domain (T1) is
# what makes math_conversation submittable. These tests prove the real
# MathConversationInput routes correctly and the exactly-one-source
# validator is enforced at the HTTP boundary.
# ---------------------------------------------------------------------------

@pytest.fixture
def conversation_client(tmp_path: Path):
    from unittest.mock import MagicMock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ai_platform.runtime import registry as deps_mod
    from ai_platform.api.routers.job_runs import make_job_runs_router
    from ai_platform.workspace.storage.structured.job_repository import JobRecord

    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    store = ArtifactService(repo, registry=MATH_CONVERSATION_ARTIFACTS)
    job_def = build_math_conversation_job_definition(_Workspace(store))

    fake_executor = MagicMock()
    fake_compute = MagicMock()
    fake_executor.submit_graph_job.return_value = JobRecord.create(
        job_type=job_def.name, graph_ref=job_def.graph_ref
    )

    deps_mod._job_definitions.clear()
    deps_mod._job_definitions[job_def.name] = job_def

    app = FastAPI()
    app.include_router(make_job_runs_router(deps_mod._job_definitions))
    app.dependency_overrides[deps_mod.get_executor] = lambda: fake_executor
    app.dependency_overrides[deps_mod.get_compute] = lambda: fake_compute
    app.dependency_overrides[deps_mod.get_job_definitions] = lambda: deps_mod._job_definitions
    return TestClient(app), fake_executor


def test_submit_question_text_form_returns_job_id(conversation_client):
    client, executor = conversation_client
    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "math_conversation", "question_text": "What is a sheaf?", "max_turns": 8},
    )
    assert resp.status_code == 200, resp.text
    assert "job_id" in resp.json()
    kwargs = executor.submit_graph_job.call_args.kwargs
    assert kwargs["job_type"] == "math_conversation"
    assert kwargs["deps_payload"]["question_text"] == "What is a sheaf?"
    assert kwargs["deps_payload"]["max_turns"] == 8


def test_submit_source_job_id_form_returns_job_id(conversation_client):
    client, executor = conversation_client
    jid = str(uuid4())
    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "math_conversation", "source_job_id": jid},
    )
    assert resp.status_code == 200, resp.text
    kwargs = executor.submit_graph_job.call_args.kwargs
    # The endpoint dumps with model_dump() (not JSON mode), so the UUID
    # stays a UUID object in the payload; the deps_factory normalizes it.
    assert str(kwargs["deps_payload"]["source_job_id"]) == jid


def test_submit_rejects_both_sources_at_http_boundary(conversation_client):
    client, _ = conversation_client
    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "math_conversation", "question_text": "x", "source_job_id": str(uuid4())},
    )
    assert resp.status_code == 422
    assert "exactly one" in resp.text


def test_submit_rejects_neither_source_at_http_boundary(conversation_client):
    client, _ = conversation_client
    resp = client.post("/jobs/runs/submit", json={"job_type": "math_conversation"})
    assert resp.status_code == 422
    assert "exactly one" in resp.text


def test_submit_rejects_unknown_field(conversation_client):
    client, _ = conversation_client
    resp = client.post(
        "/jobs/runs/submit",
        json={"job_type": "math_conversation", "question_text": "x", "bogus": 1},
    )
    assert resp.status_code == 422
    assert "bogus" in resp.text
