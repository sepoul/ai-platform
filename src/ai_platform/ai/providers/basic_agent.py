from pydantic import BaseModel
from typing import List
from pydantic_ai import Agent, FunctionToolset, Tool
from pydantic_ai.models.anthropic import AnthropicModel
from dotenv import load_dotenv
import logfire

logfire.configure()
logfire.instrument_pydantic_ai()

load_dotenv()
# 
# Claude Haiku 4.5 claude-haiku-4-5
def basic_agent(model: str = "claude-sonnet-4-5-20250929", output_type=None, instructions: str = None,
                toolsets: List[FunctionToolset] = None, tools: List[Tool] = None,
                retries=1) -> Agent:
    """
    Create a basic Pydantic AI agent using the specified model.
    """
    model = AnthropicModel(model)
    return Agent[None, output_type](model, output_type=output_type, toolsets=toolsets or [], tools=tools or [],
                 retries=retries, instructions=instructions)
