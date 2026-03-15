import os
from pathlib import Path
from typing import Optional

from google.adk.agents import LlmAgent

LIVE_MODEL_ENV_VAR = "ADK_LIVE_MODEL"
DEFAULT_LIVE_MODEL = "gemini-live-2.5-flash-native-audio"



def _load_instructions() -> str:
    instructions_path = Path(__file__).with_name("instructions.md")
    return instructions_path.read_text(encoding="utf-8").strip()



def build_subagent1(model: Optional[str] = None) -> LlmAgent:
    selected_model = model or os.getenv(LIVE_MODEL_ENV_VAR, DEFAULT_LIVE_MODEL)

    return LlmAgent(
        name="subagent1_research",
        model=selected_model,
        description="Handles focused research and grounding tasks.",
        instruction=_load_instructions(),
    )
