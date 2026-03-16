from __future__ import annotations

from google.adk.tools import ToolContext

from config import get_settings
from services.live_runtime import get_live_runtime_manager
from services.vertex_ai_image_search import get_vertex_ai_image_search_service


def search_inspiration_images(tool_context: ToolContext) -> dict[str, object]:
    tool_name = "search_inspiration_images"
    session_id = str(tool_context.state.get("session_id", "")).strip()
    saved_queries = tool_context.state.get("latest_inspiration_search_queries", [])

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
        detail="Searching for inspiration images from saved queries.",
    )

    if not isinstance(saved_queries, list):
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="Saved inspiration search queries were unavailable.",
        )
        return {
            "saved": False,
            "reason": "Saved inspiration search queries were unavailable.",
        }

    search_queries = [str(query).strip() for query in saved_queries if str(query).strip()]
    if not search_queries:
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail="No saved inspiration search queries were available.",
        )
        return {
            "saved": False,
            "reason": "No saved inspiration search queries were available.",
        }

    settings = get_settings()
    search_service = get_vertex_ai_image_search_service()

    if not search_service.is_configured():
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail=(
                "Vertex AI Search is not configured. Set "
                "VERTEX_AI_SEARCH_APP_ID. VERTEX_AI_SEARCH_LOCATION defaults to "
                "global."
            ),
        )
        return {
            "saved": False,
            "reason": (
                "Vertex AI Search is not configured. Set "
                "VERTEX_AI_SEARCH_APP_ID. VERTEX_AI_SEARCH_LOCATION defaults to "
                "global."
            ),
        }

    results_per_query = settings.inspiration_image_results_per_query
    image_results_by_query: list[dict[str, object]] = []
    total_results = 0

    try:
        for query in search_queries:
            query_results = search_service.search_images(
                query=query,
                results_per_query=results_per_query,
            )
            image_results_by_query.append(
                {
                    "query": query,
                    "results": query_results,
                }
            )
            total_results += len(query_results)
    except Exception as exc:
        detail = str(exc).strip() or "Image search failed."
        runtime.record_tool_activity(
            session_id=session_id,
            tool_name=tool_name,
            status="failed",
            detail=detail,
        )
        return {
            "saved": False,
            "reason": detail,
            "query_count": len(search_queries),
            "results_per_query": results_per_query,
        }

    tool_context.state["latest_inspiration_image_results"] = image_results_by_query
    tool_context.state["awaiting_generation_confirmation"] = True
    tool_context.state["generation_confirmed"] = False

    session_context = runtime.save_inspiration_image_results(
        session_id=session_id,
        image_results_by_query=image_results_by_query,
    )
    session_context = runtime.set_generation_confirmation(
        session_id=session_id,
        confirmed=False,
        feedback=None,
        awaiting_confirmation=True,
    )
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="succeeded",
        detail=(
            f"Searched {len(search_queries)} queries and saved {total_results} image results."
        ),
    )

    return {
        "saved": True,
        "query_count": len(search_queries),
        "total_results": total_results,
        "results_per_query": results_per_query,
        "summary": _build_result_summary(image_results_by_query),
        "session_context": session_context,
    }


def _build_result_summary(
    image_results_by_query: list[dict[str, object]],
    *,
    max_items: int = 4,
) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for group in image_results_by_query:
        if not isinstance(group, dict):
            continue
        query = str(group.get("query") or "").strip()
        results = group.get("results") or []
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            title = str(result.get("title") or "").strip()
            image_url = str(result.get("image_url") or result.get("thumbnail_url") or "")
            summary.append(
                {
                    "query": query,
                    "title": title or query or "Inspiration match",
                    "image_url": image_url.strip(),
                }
            )
            if len(summary) >= max_items:
                return summary
    return summary
