"""math_conversation domain API surface — schema-export router.

The platform's SSE log stream (`/jobs/{id}/logs/stream`) carries
`LogEntry` lines whose `message` field is JSON-encoded text. For
events tagged `source="crew_chat"`, that text parses as a
`CrewChatEvent` — but because the message is a freeform string in the
LogEntry contract, `CrewChatEvent` would otherwise never appear in
the OpenAPI schema, forcing the frontend to hand-author the type.

This module exposes `GET /math-conversation/event-types/crew-chat`
purely so `CrewChatEvent` shows up as a referenced schema, which
`gen:api` then projects into `lib/api/schema.d.ts`. The endpoint
returns a representative example, not a useful live payload — its
only job is schema discovery.

Engine-free: imports only `CrewChatEvent` (no crewai, no pydantic_graph).
"""
from __future__ import annotations

from fastapi import APIRouter

from mathai.math_conversation.crew.callbacks import CrewChatEvent


def make_math_conversation_router() -> APIRouter:
    router = APIRouter(prefix="/math-conversation", tags=["Math Conversation"])

    @router.get(
        "/event-types/crew-chat",
        response_model=CrewChatEvent,
        summary="CrewChatEvent schema (for client codegen)",
    )
    def get_crew_chat_event_schema() -> CrewChatEvent:
        """Return a representative CrewChatEvent so the OpenAPI schema
        carries the type and `gen:api` picks it up for typed FE
        parsing. Not for live consumption — live events flow over
        `/jobs/{id}/logs/stream` and are detected by JSON-parsing each
        log line and matching the `event` discriminator.
        """
        return CrewChatEvent(
            event="signed_in",
            agent_role="Algebraist",
            display_name="🧮 Algebraist",
            elapsed_seconds=0.0,
        )

    return router
