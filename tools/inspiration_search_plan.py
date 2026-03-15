from __future__ import annotations

from google.adk.tools import ToolContext

from services.live_runtime import get_live_runtime_manager

MAX_SEARCH_QUERY_COUNT = 6


def store_inspiration_search_queries(
    user_query: str,
    search_queries: list[str],
    tool_context: ToolContext,
) -> dict[str, object]:
    tool_name = "store_inspiration_search_queries"
    session_id = str(tool_context.state.get("session_id", "")).strip()
    cleaned_query = user_query.strip()
    cleaned_queries = _normalize_search_queries(search_queries)

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
        detail="Building inspiration search queries from the user brief.",
    )

    if not cleaned_query:
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="User query was empty.",
        )
        return {"saved": False, "reason": "User query was empty."}

    if not cleaned_queries:
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="No usable inspiration search queries were provided.",
        )
        return {
            "saved": False,
            "reason": "At least one non-empty search query is required.",
        }

    tool_context.state["latest_design_brief"] = cleaned_query
    tool_context.state["latest_inspiration_search_queries"] = cleaned_queries

    session_context = runtime.save_inspiration_search_plan(
        session_id=session_id,
        user_query=cleaned_query,
        search_queries=cleaned_queries,
    )
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="succeeded",
        detail=f"Saved {len(cleaned_queries)} inspiration search queries.",
    )

    return {
        "saved": True,
        "user_query": cleaned_query,
        "search_queries": cleaned_queries,
        "session_context": session_context,
    }


def _normalize_search_queries(search_queries: list[str]) -> list[str]:
    cleaned_queries: list[str] = []
    seen: set[str] = set()

    for raw_query in search_queries:
        cleaned_query = str(raw_query).strip()
        if not cleaned_query:
            continue

        normalized_query = cleaned_query.casefold()
        if normalized_query in seen:
            continue

        seen.add(normalized_query)
        cleaned_queries.append(cleaned_query)

        if len(cleaned_queries) >= MAX_SEARCH_QUERY_COUNT:
            break

    return cleaned_queries
