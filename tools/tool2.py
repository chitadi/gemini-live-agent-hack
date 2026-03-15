from google.adk.tools import ToolContext

from services.live_runtime import get_live_runtime_manager


def get_live_session_context(tool_context: ToolContext) -> dict[str, object]:
    """Return the current live-session metadata available to the agent."""
    session_id = str(tool_context.state.get("session_id", "")).strip()
    if not session_id:
        return {
            "available": False,
            "reason": "Live session ID was unavailable in tool context.",
        }

    return {
        "available": True,
        **get_live_runtime_manager().get_session_context(session_id),
    }
