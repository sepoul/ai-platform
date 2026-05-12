from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional, Any
import uuid

EventType = Literal["tool_call", "tool_result", "task_result"]


class RunEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ts: datetime = Field(default_factory=datetime.now)
    type: EventType
    tool: Optional[str] = None
    payload: Optional[Any] = None
