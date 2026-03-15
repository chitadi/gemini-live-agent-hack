from __future__ import annotations

from collections.abc import Mapping
from time import time

from services.live_runtime import get_live_runtime_manager
from services.nano_banana_generator import ReferenceImage
from services.nano_banana_generator import get_nano_banana_generator_service
from services.storage_store import get_storage_store


MAX_ROOM_REFERENCE_COUNT = 3
MAX_INSPIRATION_REFERENCE_COUNT = 4


def generate_redesign_from_session_state(
    *,
    session_state: Mapping[str, object],
) -> dict[str, object]:
    tool_name = "generate_redesign_image"
    session_id = str(session_state.get("session_id", "")).strip()
    design_brief = str(session_state.get("latest_design_brief", "")).strip()
    inspiration_queries = session_state.get("latest_inspiration_search_queries", [])
    inspiration_results = session_state.get("latest_inspiration_image_results", [])

    if not session_id:
        reason = "Live session ID was unavailable in tool context."
        return {
            "saved": False,
            "reason": reason,
            "message": "I couldn't generate the redesign because the session ID was missing.",
            "state_updates": {},
        }

    runtime = get_live_runtime_manager()
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="started",
        detail="Generating a redesign image from room snapshots and inspiration references.",
    )

    if not design_brief:
        reason = "A redesign brief must be saved before generating an image."
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message="I need a saved redesign brief before I can generate the image.",
        )

    try:
        room_images = _load_room_images(session_id=session_id)
    except Exception as exc:
        reason = str(exc).strip() or "Room snapshots could not be loaded for the generator."
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message=f"I couldn't load the saved room snapshots: {reason}",
        )

    if not room_images:
        reason = "No room snapshots were available for the generator."
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message="I need at least one saved room snapshot before I can generate the redesign.",
        )

    selected_inspiration_results = _select_inspiration_results(inspiration_results)
    try:
        inspiration_images = _load_inspiration_images(selected_inspiration_results)
    except Exception as exc:
        reason = (
            str(exc).strip()
            or "Inspiration images could not be prepared for the generator."
        )
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message=f"I couldn't prepare the saved inspiration images: {reason}",
        )

    if not inspiration_images:
        reason = "No inspiration images could be downloaded for the generator."
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message="I need saved inspiration image matches before I can generate the redesign.",
        )

    generator_service = get_nano_banana_generator_service()
    try:
        generated = generator_service.generate_redesign(
            design_brief=design_brief,
            inspiration_queries=_normalize_queries(inspiration_queries),
            room_images=room_images,
            inspiration_images=inspiration_images,
        )
    except Exception as exc:
        reason = str(exc).strip() or "Redesign image generation failed."
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message=f"I couldn't generate the redesigned image: {reason}",
        )

    timestamp_ms = int(time() * 1000)
    try:
        storage_store = get_storage_store()
        render_details = storage_store.save_generated_render(
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            image_bytes=generated["image_bytes"],
            content_type=str(generated["mime_type"]),
        )
        session_context = runtime.save_generated_render(
            session_id=session_id,
            render_details=render_details,
            model_name=str(generated["model"]),
            prompt_summary=design_brief,
        )
    except Exception as exc:
        reason = str(exc).strip() or "The redesigned image could not be saved."
        return _build_failure(
            runtime=runtime,
            session_id=session_id,
            tool_name=tool_name,
            reason=reason,
            message=f"I generated the redesign, but I couldn't save it: {reason}",
        )

    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="succeeded",
        detail="Generated and saved the first redesign render.",
    )

    return {
        "saved": True,
        "message": "The redesigned room image is ready in the UI.",
        "room_reference_count": len(room_images),
        "inspiration_reference_count": len(inspiration_images),
        "render_details": render_details,
        "session_context": session_context,
        "state_updates": {
            "latest_generated_render_path": render_details["object_path"],
            "latest_generated_render_mime_type": render_details["content_type"],
        },
    }


def _build_failure(
    *,
    runtime,
    session_id: str,
    tool_name: str,
    reason: str,
    message: str,
) -> dict[str, object]:
    runtime.record_tool_activity(
        session_id=session_id,
        tool_name=tool_name,
        status="failed",
        detail=reason,
    )
    return {
        "saved": False,
        "reason": reason,
        "message": message,
        "state_updates": {},
    }


def _load_room_images(*, session_id: str) -> list[ReferenceImage]:
    storage_store = get_storage_store()
    snapshots = storage_store.list_session_snapshots(
        session_id=session_id,
        limit=MAX_ROOM_REFERENCE_COUNT,
    )
    room_images: list[ReferenceImage] = []
    for snapshot in snapshots:
        object_path = str(snapshot.get("object_path", "")).strip()
        if not object_path:
            continue
        downloaded = storage_store.download_object(object_path)
        room_images.append(
            ReferenceImage(
                label=f"Room snapshot: {object_path.rsplit('/', 1)[-1]}",
                data=bytes(downloaded["data"]),
                mime_type=str(downloaded["content_type"] or "image/jpeg"),
            )
        )
    return room_images


def _select_inspiration_results(
    inspiration_results: object,
) -> list[dict[str, object]]:
    if not isinstance(inspiration_results, list):
        return []

    selected_results: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    for group in inspiration_results:
        if not isinstance(group, dict):
            continue

        for raw_result in group.get("results", []):
            if not isinstance(raw_result, dict):
                continue

            candidate_url = str(
                raw_result.get("thumbnail_url") or raw_result.get("image_url") or ""
            ).strip()
            if not candidate_url or candidate_url in seen_urls:
                continue

            seen_urls.add(candidate_url)
            selected_results.append(raw_result)
            break

        if len(selected_results) >= MAX_INSPIRATION_REFERENCE_COUNT:
            break

    return selected_results


def _load_inspiration_images(
    inspiration_results: list[dict[str, object]],
) -> list[ReferenceImage]:
    generator_service = get_nano_banana_generator_service()
    inspiration_images: list[ReferenceImage] = []

    for index, result in enumerate(inspiration_results, start=1):
        candidate_urls = [
            str(result.get("thumbnail_url") or "").strip(),
            str(result.get("image_url") or "").strip(),
        ]
        label = (
            str(result.get("title") or "").strip()
            or str(result.get("query") or "").strip()
            or f"Inspiration reference {index}"
        )

        for url in candidate_urls:
            if not url:
                continue
            try:
                inspiration_images.append(
                    generator_service.download_reference_image(
                        url=url,
                        fallback_label=label,
                    )
                )
                break
            except Exception:
                continue

    return inspiration_images


def _normalize_queries(raw_queries: object) -> list[str]:
    if not isinstance(raw_queries, list):
        return []
    return [str(query).strip() for query in raw_queries if str(query).strip()]
