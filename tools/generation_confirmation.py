from __future__ import annotations

from google.adk.tools import ToolContext

from services.live_runtime import get_live_runtime_manager


def store_generation_confirmation(
    approved: bool,
    feedback: str,
    tool_context: ToolContext,
) -> dict[str, object]:
    tool_name = "store_generation_confirmation"
    session_id = str(tool_context.state.get("session_id", "")).strip()
    cleaned_feedback = str(feedback or "").strip()

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
        detail="Saving generation confirmation.",
    )

    tool_context.state["generation_confirmed"] = bool(approved)
    tool_context.state["generation_feedback"] = cleaned_feedback
    tool_context.state["awaiting_generation_confirmation"] = False

    session_context = runtime.set_generation_confirmation(
        session_id=session_id,
        confirmed=bool(approved),
        feedback=cleaned_feedback,
        awaiting_confirmation=False,
    )

    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="succeeded",
        detail="Generation confirmation saved.",
    )

    return {
        "saved": True,
        "approved": bool(approved),
        "feedback": cleaned_feedback,
        "session_context": session_context,
    }
