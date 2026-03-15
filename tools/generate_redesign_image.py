from __future__ import annotations

from google.adk.tools import ToolContext

from services.redesign_generation import generate_redesign_from_session_state


def generate_redesign_image(tool_context: ToolContext) -> dict[str, object]:
    result = generate_redesign_from_session_state(
        session_state=tool_context.state.to_dict()
    )

    for key, value in result.get("state_updates", {}).items():
        tool_context.state[key] = value

    return result
