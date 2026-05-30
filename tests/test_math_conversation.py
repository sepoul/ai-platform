"""Tests for the math_conversation domain skeleton (T1), artifact schema
(T2), and the crew chat-event emitters (T4).

All of this is CrewAI-free and needs no network — the crew internals
(T5/T6) slot into `RunCrewStep` later without touching these contracts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

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
from mathai.math_conversation.control import build_math_conversation_control
from mathai.math_conversation.execution import build_math_conversation_execution
from mathai.math_conversation.workflow import (
    MathConversationDeps,
    SeedStep,
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

def _patch_panel(monkeypatch, *, conclude_after: int | None = None, content: str = "stub"):
    """Replace `build_panel` / `build_turn_crew` so RunCrewStep doesn't import
    crewai in the test env (the engine ships only in the worker[crewai] image).

    The fake panel has a single Algebraist agent; the fake per-turn crew
    returns `content` and zero cost. If `conclude_after` is set, the
    panel's `ConcludeSignal` flips after that many calls to `kickoff` —
    used to exercise the early-exit path.
    """
    from types import SimpleNamespace
    from mathai.math_conversation.crew.crew import Panel
    from mathai.math_conversation.crew.tools import ConcludeSignal

    signal = ConcludeSignal()
    fake_panel = Panel(
        agents_by_name={"algebraist": object()},
        display_by_name={"algebraist": "🧮 Algebraist"},
        role_by_name={"algebraist": "Algebraist"},
        conclude_signal=signal,
        order=("algebraist",),
    )
    fake_output = SimpleNamespace(raw=content, token_usage=SimpleNamespace(total_cost=0.0))
    kickoff_count = {"n": 0}

    def _kickoff():
        kickoff_count["n"] += 1
        if conclude_after is not None and kickoff_count["n"] >= conclude_after:
            signal.fired = True
            signal.reason = "test conclude"
        return fake_output

    fake_crew = SimpleNamespace(kickoff=_kickoff)
    monkeypatch.setattr("mathai.math_conversation.workflow.build_panel", lambda: fake_panel)
    # seed_context arrives as a keyword from RunCrewStep when source_job_id
    # hydration populates state.seed_context; absorb it so the stub matches
    # the real signature.
    monkeypatch.setattr(
        "mathai.math_conversation.workflow.build_turn_crew",
        lambda panel, persona_name, transcript, seed_question, *, seed_context=None: fake_crew,
    )
    return signal, kickoff_count


def _seeded_artifact_service(tmp_path: Path, source_job_id: UUID, **fields):
    """Build an ArtifactService with both math_qa + math_conversation
    types registered, pre-populated with the math_qa artifacts a source
    job would have produced. `fields` overrides per-artifact text:

        question_text="...", answer_text="...", latex_source="...",
        figure_spec={...}, topic="...", difficulty="...".

    Omitted fields produce that artifact with reasonable defaults; pass
    `<name>=None` to omit the artifact entirely (used to test partial
    source-job artifact sets).
    """
    from mathai.math_qa.artifacts import (
        MATH_QA_ARTIFACTS,
        FigureArtifact,
        GeneratedAnswerArtifact,
        LatexAnswerArtifact,
        MathQuestionArtifact,
    )

    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    registry = {**MATH_QA_ARTIFACTS, **MATH_CONVERSATION_ARTIFACTS}
    service = ArtifactService(repo, registry=registry)

    sid = str(source_job_id)
    if fields.get("question_text", "What is a group?") is not None:
        service.put(MathQuestionArtifact(
            created_by_job=sid,
            question_text=fields.get("question_text", "What is a group?"),
            topic=fields.get("topic"),
            difficulty=fields.get("difficulty"),
        ))
    if fields.get("answer_text", "A group is a set with...") is not None:
        service.put(GeneratedAnswerArtifact(
            created_by_job=sid,
            answer_text=fields.get("answer_text", "A group is a set with..."),
        ))
    if fields.get("latex_source", "G = \\langle a, b \\rangle") is not None:
        service.put(LatexAnswerArtifact(
            created_by_job=sid,
            latex_source=fields.get("latex_source", "G = \\langle a, b \\rangle"),
        ))
    if fields.get("figure_spec", {"template": "group-table"}) is not None:
        service.put(FigureArtifact(
            created_by_job=sid,
            template="group-table",
            spec=fields.get("figure_spec", {"template": "group-table"}),
        ))
    return service


@pytest.mark.anyio
async def test_graph_runs_to_end_with_question_text(monkeypatch):
    _patch_panel(monkeypatch)
    state = MathConversationState()
    deps = MathConversationDeps(question_text="What is a manifold?", max_turns=1)
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.seed_question == "What is a manifold?"
    assert state.max_turns == 1
    assert state.stop_reason == "max_turns"
    assert len(state.turns) == 1 and state.turns[0].content == "stub"


@pytest.mark.anyio
async def test_graph_runs_to_end_with_source_job_id(monkeypatch, tmp_path: Path):
    _patch_panel(monkeypatch)
    jid = uuid4()
    state = MathConversationState()
    deps = MathConversationDeps(
        source_job_id=jid,
        max_turns=1,
        artifact_api=_seeded_artifact_service(tmp_path, jid),
    )
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.source_job_id == jid
    assert state.seed_question == "What is a group?"
    assert state.stop_reason == "max_turns"


# ---------------------------------------------------------------------------
# SeedStep hydration — the source_job_id path projects a prior math_qa
# job's artifacts into state.seed_context so the panel can refine the
# single-shot answer instead of starting from scratch.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_seedstep_hydrates_full_seed_context_from_source_job(monkeypatch, tmp_path: Path):
    _patch_panel(monkeypatch)
    jid = uuid4()
    state = MathConversationState()
    deps = MathConversationDeps(
        source_job_id=jid,
        max_turns=1,
        artifact_api=_seeded_artifact_service(
            tmp_path,
            jid,
            question_text="Define homotopy.",
            answer_text="A homotopy is a continuous deformation...",
            latex_source="H: X \\times [0,1] \\to Y",
            topic="topology",
            difficulty="intermediate",
        ),
    )
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.seed_question == "Define homotopy."
    assert state.seed_context is not None
    assert state.seed_context["answer"] == "A homotopy is a continuous deformation..."
    assert state.seed_context["latex"] == "H: X \\times [0,1] \\to Y"
    assert state.seed_context["topic"] == "topology"
    assert state.seed_context["difficulty"] == "intermediate"
    assert state.seed_context["figure"] == {"template": "group-table"}  # default fixture figure


@pytest.mark.anyio
async def test_seedstep_errors_when_artifact_api_missing_for_source_job_path():
    """source_job_id without an artifact_api is a wiring bug — the worker
    bootstrap must inject the platform's ArtifactService. Loud-fail is
    correct; silent fallback would hide the misconfiguration.
    """
    state = MathConversationState()
    deps = MathConversationDeps(source_job_id=uuid4(), max_turns=1)  # no artifact_api
    with pytest.raises(RuntimeError, match="artifact_api is required"):
        await SeedStep().run(_FakeContext(state=state, deps=deps))


@pytest.mark.anyio
async def test_seedstep_errors_when_source_job_has_no_math_question(monkeypatch, tmp_path: Path):
    """A panel without the original question has nothing to anchor on —
    fail explicitly rather than silently brainstorming about nothing.
    """
    jid = uuid4()
    state = MathConversationState()
    deps = MathConversationDeps(
        source_job_id=jid,
        max_turns=1,
        artifact_api=_seeded_artifact_service(tmp_path, jid, question_text=None),
    )
    with pytest.raises(RuntimeError, match="no math_question artifact"):
        await SeedStep().run(_FakeContext(state=state, deps=deps))


@pytest.mark.anyio
async def test_seedstep_hydrates_partial_seed_context_when_optional_artifacts_missing(
    monkeypatch, tmp_path: Path,
):
    """Missing latex / figure / answer are tolerated (set to None in
    seed_context); only the question is required.
    """
    _patch_panel(monkeypatch)
    jid = uuid4()
    state = MathConversationState()
    deps = MathConversationDeps(
        source_job_id=jid,
        max_turns=1,
        artifact_api=_seeded_artifact_service(
            tmp_path, jid,
            answer_text=None, latex_source=None, figure_spec=None,
        ),
    )
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.seed_question == "What is a group?"
    assert state.seed_context["answer"] is None
    assert state.seed_context["latex"] is None
    assert state.seed_context["figure"] is None


@dataclass
class _FakeContext:
    """Minimal stand-in for `GraphRunContext` so SeedStep failure paths
    can be exercised without a full `math_conversation_graph.run(...)`
    (which would otherwise swallow the raise inside the engine).
    """
    state: MathConversationState
    deps: MathConversationDeps


@pytest.mark.anyio
async def test_conclude_flag_at_entry_short_circuits_loop(monkeypatch):
    """If a resumed checkpoint already has concluded=True, RunCrewStep
    must skip the panel loop (the defensive guard) and let FinalizeStep
    persist whatever turns are on state.
    """
    _, kickoff_count = _patch_panel(monkeypatch)
    state = MathConversationState(concluded=True)
    deps = MathConversationDeps(question_text="x", max_turns=3)
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.stop_reason == "concluded"
    assert kickoff_count["n"] == 0  # the loop never ran


@pytest.mark.anyio
async def test_panel_runs_to_max_turns_when_no_conclude(monkeypatch):
    _patch_panel(monkeypatch)
    state = MathConversationState()
    deps = MathConversationDeps(question_text="x", max_turns=4)
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.stop_reason == "max_turns"
    assert len(state.turns) == 4
    # Round-robin over a 1-persona panel keeps the same speaker; verify the
    # indices come out 0..3 contiguous.
    assert [t.turn_index for t in state.turns] == [0, 1, 2, 3]


@pytest.mark.anyio
async def test_panel_short_circuits_when_conclude_fires_mid_run(monkeypatch):
    """The conclude tool is the design's polite-stop path. Flipping the
    signal on the 2nd kickoff must terminate the loop before max_turns
    and mark `state.concluded=True`.
    """
    _patch_panel(monkeypatch, conclude_after=2)
    state = MathConversationState()
    deps = MathConversationDeps(question_text="x", max_turns=10)
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    assert state.concluded is True
    assert state.stop_reason == "concluded"
    assert len(state.turns) == 2  # broke on turn 1 (index 1)


@pytest.mark.anyio
async def test_panel_emits_signed_in_and_out_for_each_persona(monkeypatch):
    """Roll call / roll out frame the conversation in the live event stream."""
    _patch_panel(monkeypatch)
    state = MathConversationState()
    deps = MathConversationDeps(question_text="x", max_turns=1)
    fake_logger = _FakeLogger()
    deps.logger = fake_logger  # type: ignore[assignment]
    await math_conversation_graph.run(SeedStep(), state=state, deps=deps)
    events = [CrewChatEvent.model_validate_json(m) for m in fake_logger.messages
              if m.startswith("{") and '"event"' in m]
    event_names = [e.event for e in events]
    assert event_names[0] == "signed_in"
    assert event_names[-1] == "signed_out"
    assert "message" in event_names
    assert "status" in event_names


# ---------------------------------------------------------------------------
# T1 — job definition: deps_factory, persist, fetch_result
# ---------------------------------------------------------------------------

class _Workspace:
    def __init__(self, store):
        self.artifact_store = store


@pytest.fixture
def job_def(tmp_path: Path):
    """Returns (execution, control, store) — deps_factory/persist live on the
    execution plane, fetch_result on the control plane."""
    repo = LocalArtifactRepository(LocalRepositoryConfig(root_dir=str(tmp_path), prefix="artifacts"))
    store = ArtifactService(repo, registry=MATH_CONVERSATION_ARTIFACTS)
    ws = _Workspace(store)
    return build_math_conversation_execution(ws), build_math_conversation_control(ws), store


def test_deps_factory_parses_payload(job_def):
    jd, _, _ = job_def
    jid = uuid4()
    deps = jd.deps_factory({"source_job_id": str(jid), "max_turns": 7})
    assert deps.source_job_id == jid
    assert deps.max_turns == 7
    assert deps.question_text is None


def test_persist_mints_conversation_artifact(job_def):
    jd, _, store = job_def
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
    _, jd, store = job_def
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
    """Captures emitted messages so we can assert the event sequence.

    Crew-chat events arrive via `emit` (raw JSON). Plain `log.info(...)`
    /`log.error(...)` calls (used by `RunCrewStep` for human-readable
    progress) are prefixed so callers can filter them out by string
    shape — crew events parse as JSON with an `event` key; the tagged
    log lines don't.
    """

    def __init__(self):
        self.job_id = "fake"
        self.stage = None
        self.source = "test"
        self.messages: list[str] = []

    async def emit(self, message: str, *, level: str = "info") -> None:
        self.messages.append(message)

    async def info(self, message: str) -> None:
        self.messages.append(f"[info] {message}")

    async def error(self, message: str) -> None:
        self.messages.append(f"[error] {message}")

    async def warning(self, message: str) -> None:
        self.messages.append(f"[warn] {message}")

    async def debug(self, message: str) -> None:
        self.messages.append(f"[debug] {message}")

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


def test_crew_chat_event_schema_endpoint_round_trips():
    """The schema-export endpoint is the only reason `CrewChatEvent`
    appears in the OpenAPI schema. If this breaks, `gen:api` stops
    surfacing the type and the math-ui chat parser falls back to
    hand-authored types — silent FE drift. Tested as a real HTTP call so
    the round-trip (FastAPI → response_model → JSON → parse) is real.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mathai.math_conversation.api import make_math_conversation_router

    app = FastAPI()
    app.include_router(make_math_conversation_router())
    client = TestClient(app)
    resp = client.get("/math-conversation/event-types/crew-chat")
    assert resp.status_code == 200
    event = CrewChatEvent.model_validate(resp.json())
    assert event.event == "signed_in"
    assert event.agent_role == "Algebraist"


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
    assert persona.model.startswith("anthropic/")
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
    assert reparsed.model.startswith("anthropic/")


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
    job_control = build_math_conversation_control(_Workspace(store))

    fake_executor = MagicMock()
    fake_compute = MagicMock()
    fake_executor.submit_graph_job.return_value = JobRecord.create(
        job_type=job_control.name, graph_ref=job_control.label
    )

    deps_mod._job_controls.clear()
    deps_mod._job_controls[job_control.name] = job_control

    app = FastAPI()
    app.include_router(make_job_runs_router(deps_mod._job_controls))
    app.dependency_overrides[deps_mod.get_executor] = lambda: fake_executor
    app.dependency_overrides[deps_mod.get_compute] = lambda: fake_compute
    app.dependency_overrides[deps_mod.get_job_controls] = lambda: deps_mod._job_controls
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
