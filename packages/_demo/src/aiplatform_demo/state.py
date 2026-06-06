"""Demo graph state — one field, just enough to thread the input
through the single node into the artifact."""
from __future__ import annotations

from typing import Optional

from ai_platform.jobs.base_state import BaseJobState


class DemoState(BaseJobState):
    message: Optional[str] = None
    echoed: Optional[str] = None
