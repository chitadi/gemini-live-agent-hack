from __future__ import annotations

import asyncio
import os
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types as genai_types

from services.redesign_generation import generate_redesign_from_session_state
from tools.generate_redesign_image import generate_redesign_image


def _load_instruction_template() -> str:
    instructions_path = Path(__file__).with_name("instructions.md")
    return instructions_path.read_text(encoding="utf-8").strip()


async def _run_generator_workflow(
    callback_context: CallbackContext,
) -> genai_types.Content:
    result = await asyncio.to_thread(
        generate_redesign_from_session_state,
        session_state=callback_context.state.to_dict(),
    )

    for key, value in result.get("state_updates", {}).items():
        callback_context.state[key] = value

    message = str(
        result.get("message")
        or "I couldn't complete the redesign generation request."
    ).strip()
    return genai_types.Content(
        role="model",
        parts=[genai_types.Part.from_text(text=message)],
    )


generator_agent = LlmAgent(
    name="generator",
    model=os.getenv("ADK_TEXT_MODEL", "gemini-2.5-flash"),
    description=(
        "Creates a redesigned room render from saved room snapshots, the saved brief, "
        "and saved inspiration image matches."
    ),
    instruction=_load_instruction_template(),
    before_agent_callback=_run_generator_workflow,
    tools=[generate_redesign_image],
)
