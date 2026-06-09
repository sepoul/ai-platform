"""Demo graph state — one field, just enough to thread the input
through the single node into the artifact."""
from __future__ import annotations

from typing import Optional

from ai_platform.jobs.base_state import BaseJobState


class DemoState(BaseJobState):
    message: Optional[str] = None
    echoed: Optional[str] = None
    # Carried through from input so `_persist` can stamp the produced
    # artifact with the uploaded blob's ref (PR-1 UAT loop).
    storage_ref: Optional[str] = None
    content_type: Optional[str] = None
    byte_size: Optional[int] = None
