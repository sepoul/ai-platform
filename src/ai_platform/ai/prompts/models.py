from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Prompt(BaseModel):
    """A first-class prompt stored in the prompt registry.

    Instructions describe what the prompt expects to receive.
    Agents are responsible for augmenting the prompt with the actual
    data at execution time.
    """
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str                       # unique key, e.g. "concept.math_concept"
    domain: str                     # grouping key, e.g. "concept"
    description: str
    instructions: str               # instruction text (editable via API)
    version: str = "0.1.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def bump_version(self) -> str:
        """Return a copy of this prompt with the patch version bumped and updated_at set."""
        major, minor, patch = self.version.split(".")
        new_patch = str(int(patch) + 1)
        new_version = f"{major}.{minor}.{new_patch}"
        return new_version
    
    def update_instructions(self, new_instructions: str) -> "Prompt":
        """Return a new Prompt instance with updated instructions, version bumped, and a fresh id."""
        return Prompt(
            name=self.name,
            domain=self.domain,
            description=self.description,
            instructions=new_instructions,
            version=self.bump_version(),
        )

class PromptStore(BaseModel):
    """Store wrapper for all Prompts (single-file pattern)."""
    model_config = ConfigDict(extra="forbid")

    items: Dict[str, Prompt] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)


class PromptSnapshot(BaseModel):
    """Frozen snapshot of a prompt captured at job submission time."""
    name: str
    version: str
    instructions: str


class PromptExecution(BaseModel):
    """Record of a single prompt execution against an agent.

    Agents persist this during graph execution so the API can
    show the full picture of what was actually passed.
    """
    id: str = Field(default_factory=lambda: uuid4().hex)
    prompt_name: str
    prompt_version: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_name: Optional[str] = None
    output_type: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class PromptExecutionStore(BaseModel):
    """Store wrapper for all PromptExecutions (single-file pattern)."""
    model_config = ConfigDict(extra="forbid")

    items: Dict[str, PromptExecution] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)
