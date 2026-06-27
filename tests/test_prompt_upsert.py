"""Prompt deploy is upsert-by-content (issue #59).

`POST /prompts` used to be get-or-create on `name`: once a name existed,
edited instructions were silently dropped — a deploy reported success but
the platform kept serving stale content. These tests pin the new
upsert-by-content behavior at both the registry and the router.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_platform.ai.prompts.models import Prompt
from ai_platform.api.routers import prompts as prompts_mod
from ai_platform.runtime import registry as deps_mod
from ai_platform.workspace.prompt_registry import PromptRegistry


class _MemPromptRepo:
    """Minimal in-memory prompt repo (the registry only needs list/put/get)."""

    def __init__(self) -> None:
        self.items: dict[str, Prompt] = {}

    def list(self) -> list[Prompt]:
        return list(self.items.values())

    def put(self, prompt: Prompt) -> Prompt:
        self.items[prompt.id] = prompt
        return prompt

    def get(self, prompt_id: str) -> Prompt:
        return self.items[prompt_id]


def _registry() -> PromptRegistry:
    return PromptRegistry(_MemPromptRepo())


def _prompt(instructions: str, *, name: str = "d.x", version: str = "0.1.0") -> Prompt:
    return Prompt(name=name, domain="d", description="desc", instructions=instructions, version=version)


# ---------------------------------------------------------------------------
# Registry.upsert
# ---------------------------------------------------------------------------

def test_upsert_creates_when_absent():
    reg = _registry()
    _, action = reg.upsert(_prompt("v1"))
    assert action == "created"
    assert reg.get_prompt("d.x").instructions == "v1"


def test_upsert_is_noop_when_identical():
    reg = _registry()
    reg.upsert(_prompt("v1"))
    _, action = reg.upsert(_prompt("v1"))
    assert action == "unchanged"
    # No version churn for identical content.
    assert reg.get_prompt("d.x").version == "0.1.0"


def test_upsert_version_bumps_when_instructions_change():
    reg = _registry()
    reg.upsert(_prompt("v1"))
    prompt, action = reg.upsert(_prompt("v2"))
    assert action == "updated"
    latest = reg.get_prompt("d.x")
    assert latest.instructions == "v2"
    assert latest.version == "0.1.1"  # bumped from the latest, not the request


def test_upsert_ignores_incoming_version_and_bumps_from_latest():
    """The export-manifest catalog ships a fixed version for every prompt,
    so the fix must not rely on the request's version — it bumps from the
    stored latest."""
    reg = _registry()
    reg.upsert(_prompt("v1", version="0.1.0"))
    reg.upsert(_prompt("v2", version="9.9.9"))  # bogus high version in request
    assert reg.get_prompt("d.x").version == "0.1.1"


# ---------------------------------------------------------------------------
# POST /prompts router
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    fake = MagicMock()
    fake.prompt_registry = _registry()
    app = FastAPI()
    app.include_router(prompts_mod.router)
    app.dependency_overrides[deps_mod.get_platform_client] = lambda: fake
    return TestClient(app)


def _body(instructions: str) -> dict:
    return {"name": "d.x", "domain": "d", "description": "desc", "instructions": instructions}


def test_post_reports_created_updated_unchanged_and_serves_latest():
    client = _client()

    r1 = client.post("/prompts", json=_body("v1"))
    assert r1.status_code == 200, r1.text
    assert r1.json()["action"] == "created"
    assert r1.json()["version"] == "0.1.0"

    # Re-deploying identical content is a safe no-op (no version churn).
    r2 = client.post("/prompts", json=_body("v1"))
    assert r2.json()["action"] == "unchanged"
    assert r2.json()["version"] == "0.1.0"

    # The edit that used to be silently dropped now lands (version-bumped).
    r3 = client.post("/prompts", json=_body("v2"))
    assert r3.json()["action"] == "updated"
    assert r3.json()["version"] == "0.1.1"

    # And GET serves the new content — the bug's actual symptom is gone.
    assert client.get("/prompts/d.x").json()["instructions"] == "v2"
