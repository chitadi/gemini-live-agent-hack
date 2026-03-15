from google.adk.tools import ToolContext

from services.live_runtime import get_live_runtime_manager


def persist_snapshot_observation(
    note: str, tool_context: ToolContext
) -> dict[str, object]:
    """Persist a concise observation from the latest room snapshot."""
    session_id = str(tool_context.state.get("session_id", "")).strip()
    cleaned = note.strip()

    if not session_id:
        return {
            "saved": False,
            "reason": "Live session ID was unavailable in tool context.",
        }

    if not cleaned:
        return {
            "saved": False,
            "reason": "Observation note was empty.",
        }

    tool_context.state["last_snapshot_observation"] = cleaned
    session_context = get_live_runtime_manager().persist_snapshot_observation(
        session_id=session_id,
        note=cleaned,
    )
    return {
        "saved": True,
        "note": cleaned,
        "session_context": session_context,
    }
