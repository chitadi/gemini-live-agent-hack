from __future__ import annotations

from google.adk.tools import ToolContext

from services.live_runtime import get_live_runtime_manager


def store_vibe_memory(vibe_memory: str, tool_context: ToolContext) -> dict[str, object]:
    tool_name = "store_vibe_memory"
    session_id = str(tool_context.state.get("session_id", "")).strip()
    cleaned_memory = str(vibe_memory or "").strip()

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
        detail="Saving vibe memory from user preferences.",
    )

    if not cleaned_memory:
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="Vibe memory was empty.",
        )
        return {"saved": False, "reason": "Vibe memory was empty."}

    room_memory = str(tool_context.state.get("room_memory", "") or "").strip()
    if not room_memory:
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="Room memory must be saved before vibe memory.",
        )
        return {
            "saved": False,
            "reason": "Room memory must be saved before vibe memory.",
        }

    tool_context.state["vibe_memory"] = cleaned_memory

    session_context = runtime.save_vibe_memory(
        session_id=session_id,
        vibe_memory=cleaned_memory,
    )
    session_context = runtime.set_flow_state(
        session_id=session_id,
        flow_state="vibe",
    )
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="succeeded",
        detail="Vibe memory saved.",
    )

    return {
        "saved": True,
        "vibe_memory": cleaned_memory,
        "session_context": session_context,
    }
