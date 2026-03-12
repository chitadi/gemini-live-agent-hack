import os
from pathlib import Path

from google.adk.agents import LlmAgent

from loader import load_tools
from subagents.subagent1.agent_factory import build_subagent1
from subagents.subagent2.agent_factory import build_subagent2

MODEL_ENV_VAR = "ADK_LIVE_MODEL"
DEFAULT_LIVE_MODEL = "gemini-2.5-flash-live-001"



def _load_instructions() -> str:
    instructions_path = Path(__file__).with_name("instructions.md")
    if instructions_path.exists():
        return instructions_path.read_text(encoding="utf-8").strip()

    return (
        "You are a live, multimodal Gemini coordinator agent. "
        "Delegate specific tasks to subagents when useful."
    )


selected_model = os.getenv(MODEL_ENV_VAR, DEFAULT_LIVE_MODEL)

subagent1 = build_subagent1(model=selected_model)
subagent2 = build_subagent2(model=selected_model)

# ADK convention: keep the entrypoint agent named root_agent.
root_agent = LlmAgent(
    name="gemini_live_coordinator",
    model=selected_model,
    description="Coordinator agent for live Gemini interactions with extensible tools.",
    instruction=_load_instructions(),
    tools=load_tools(),
    sub_agents=[subagent1, subagent2],
)
