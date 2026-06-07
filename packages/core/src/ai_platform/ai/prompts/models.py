from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai_platform.utilities.time import utc_now


# A registry entry is one of: a plain instruction prompt, a CrewAI
# persona, or a CrewAI skill. Personae and skills store their full
# Markdown (YAML front-matter + body) in `instructions`; the
# math_conversation registry helpers parse them into PersonaSpec /
# SkillSpec. Plain prompts have no front-matter.
PromptKind = Literal["prompt", "persona", "skill"]


class Prompt(BaseModel):
    """A first-class prompt stored in the prompt registry.

    Instructions describe what the prompt expects to receive.
    Agents are responsible for augmenting the prompt with the actual
    data at execution time.
    """
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str                       # unique key, e.g. "math_qa.answer"
    domain: str                     # grouping key, e.g. "math_qa"
    description: str
    instructions: str               # instruction text (editable via API)
    kind: PromptKind = "prompt"     # discriminates plain prompts from personae / skills
    version: str = "0.1.0"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

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
            kind=self.kind,
            version=self.bump_version(),
        )

class PromptStore(BaseModel):
    """Store wrapper for all Prompts (single-file pattern)."""
    model_config = ConfigDict(extra="forbid")

    items: Dict[str, Prompt] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


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
    executed_at: datetime = Field(default_factory=utc_now)
    model_name: Optional[str] = None
    output_type: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class PromptExecutionStore(BaseModel):
    """Store wrapper for all PromptExecutions (single-file pattern)."""
    model_config = ConfigDict(extra="forbid")

    items: Dict[str, PromptExecution] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)
