from __future__ import annotations

from google.adk.tools import ToolContext

from services.live_runtime import get_live_runtime_manager


def store_room_memory(room_memory: str, tool_context: ToolContext) -> dict[str, object]:
    tool_name = "store_room_memory"
    session_id = str(tool_context.state.get("session_id", "")).strip()
    cleaned_memory = str(room_memory or "").strip()

    if not session_id:
        return {
            "saved": False,
            "reason": "Live session ID was unavailable in tool context.",
        }

    runtime = get_live_runtime_manager()
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="started",
        detail="Saving room memory from the scan.",
    )

    if not cleaned_memory:
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="Room memory was empty.",
        )
        return {"saved": False, "reason": "Room memory was empty."}

    tool_context.state["room_memory"] = cleaned_memory

    session_context = runtime.save_room_memory(
        session_id=session_id,
        room_memory=cleaned_memory,
    )
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="succeeded",
        detail="Room memory saved.",
    )

    return {
        "saved": True,
        "room_memory": cleaned_memory,
        "session_context": session_context,
    }
