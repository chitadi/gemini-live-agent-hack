import os
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from loader import load_tools
from services.live_runtime import get_live_runtime_manager

MODEL_ENV_VAR = "ADK_LIVE_MODEL"
DEFAULT_LIVE_MODEL = "gemini-live-2.5-flash-native-audio"


def _load_instruction_template() -> str:
    instructions_path = Path(__file__).with_name("instructions.md")
    if instructions_path.exists():
        return instructions_path.read_text(encoding="utf-8").strip()

    return (
        "You are a live interior designer guiding a room walkthrough. "
        "Keep replies short and clearly separate observation from inference."
    )


async def _build_instruction(readonly_context: ReadonlyContext) -> str:
    session_id = str(readonly_context.state.get("session_id", "")).strip()
    live_context = get_live_runtime_manager().build_instruction_context(session_id)
    return f"{_load_instruction_template()}\n\n{live_context}"


selected_model = os.getenv(MODEL_ENV_VAR, DEFAULT_LIVE_MODEL)

# ADK convention: keep the entrypoint agent named root_agent.
root_agent = LlmAgent(
    name="gemini_live_coordinator",
    model=selected_model,
    description="Voice-first interior-design guide for live room walkthroughs.",
    instruction=_build_instruction,
    tools=load_tools(),
)
