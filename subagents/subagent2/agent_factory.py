import os
from pathlib import Path
from typing import Optional

from google.adk.agents import LlmAgent

LIVE_MODEL_ENV_VAR = "ADK_LIVE_MODEL"
DEFAULT_LIVE_MODEL = "gemini-2.5-flash-live-001"



def _load_instructions() -> str:
    instructions_path = Path(__file__).with_name("instructions.md")
    return instructions_path.read_text(encoding="utf-8").strip()



def build_subagent2(model: Optional[str] = None) -> LlmAgent:
    selected_model = model or os.getenv(LIVE_MODEL_ENV_VAR, DEFAULT_LIVE_MODEL)

    return LlmAgent(
        name="subagent2_response_designer",
        model=selected_model,
        description="Designs final response structure for live conversations.",
        instruction=_load_instructions(),
    )
