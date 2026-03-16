from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from time import time
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import WebSocket
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.agents.run_config import ToolThreadPoolConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from config import get_settings
from services.firestore_store import get_firestore_store
from services.storage_store import get_storage_store


logger = logging.getLogger(__name__)

DEMO_USER_ID = "demo-user"
_DEDUPABLE_WEBSOCKET_MESSAGE_TYPES = {"status", "agent_text", "turn_state"}


def _summarize_websocket_payload(payload: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {
        "type": payload.get("type"),
    }

    if "state" in payload:
        summary["state"] = payload.get("state")
    if "mime_type" in payload:
        summary["mime_type"] = payload.get("mime_type")
    if "turn_complete" in payload:
        summary["turn_complete"] = payload.get("turn_complete")
    if "interrupted" in payload:
        summary["interrupted"] = payload.get("interrupted")
    if "text" in payload:
        summary["text_preview"] = str(payload.get("text") or "")[:120]
    if "detail" in payload:
        summary["detail_preview"] = str(payload.get("detail") or "")[:120]
    if "data" in payload:
        summary["has_data"] = True

    return summary


def _fingerprint_websocket_payload(payload: dict[str, object]) -> str | None:
    message_type = str(payload.get("type") or "").strip()
    if message_type not in _DEDUPABLE_WEBSOCKET_MESSAGE_TYPES:
        return None

    fingerprint_payload = {
        "type": message_type,
        "state": payload.get("state"),
        "detail": payload.get("detail"),
        "text": payload.get("text"),
        "turn_complete": payload.get("turn_complete"),
        "interrupted": payload.get("interrupted"),
    }
    return json.dumps(fingerprint_payload, sort_keys=True, default=str)


async def _send_ws_json(
    *,
    websocket: WebSocket,
    session_id: str,
    dedupe_cache: dict[str, str],
    payload: dict[str, object],
) -> None:
    payload_summary = _summarize_websocket_payload(payload)
    fingerprint = _fingerprint_websocket_payload(payload)
    if fingerprint is not None:
        message_type = str(payload.get("type") or "").strip()
        previous_fingerprint = dedupe_cache.get(message_type)
        if previous_fingerprint == fingerprint:
            logger.info(
                "ws_out_deduped session_id=%s payload=%s",
                session_id,
                payload_summary,
            )
            return
        dedupe_cache[message_type] = fingerprint

    logger.info(
        "ws_out session_id=%s payload=%s",
        session_id,
        payload_summary,
    )
    await websocket.send_json(payload)


@dataclass
class LiveSessionMetadata:
    session_id: str
    user_id: str
    created_at: float
    status: str
    snapshot_interval_ms: int
    latest_snapshot_path: str | None = None
    latest_snapshot_timestamp_ms: int | None = None
    snapshot_count: int = 0
    flow_state: str = "room"
    awaiting_generation_confirmation: bool = False
    generation_confirmed: bool = False
    generation_feedback: str | None = None
    latest_design_brief: str | None = None
    latest_inspiration_search_queries: list[str] = field(default_factory=list)
    latest_inspiration_image_results: list[dict[str, object]] = field(
        default_factory=list
    )
    room_memory: str | None = None
    vibe_memory: str | None = None
    latest_generated_render_path: str | None = None
    latest_generated_render_mime_type: str | None = None
    latest_tool_name: str | None = None
    latest_tool_status: str | None = None
    latest_tool_detail: str | None = None
    latest_user_transcript: str | None = None
    latest_agent_transcript: str | None = None
    last_websocket_payload_fingerprints: dict[str, str] = field(default_factory=dict)
    primer_sent: bool = False


class LiveRuntimeManager:
    def __init__(self) -> None:
        self._session_service = InMemorySessionService()
        self._runner: Runner | None = None
        self._sessions: dict[str, LiveSessionMetadata] = {}
        self._firestore_store = get_firestore_store()
        self._storage_store = get_storage_store()

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            from agents.agent import root_agent

            settings = get_settings()
            self._runner = Runner(
                app_name=settings.app_name,
                agent=root_agent,
                session_service=self._session_service,
            )
        return self._runner

    async def create_session(self) -> LiveSessionMetadata:
        settings = get_settings()
        session_id = uuid4().hex
        initial_state = {
            "session_id": session_id,
            "app_name": settings.app_name,
            "snapshot_interval_ms": settings.snapshot_interval_ms,
            "live_persona": "fun interior designer",
            "flow_state": "room",
            "scan_guidance_hint": (
                "Guide the scan in short steps like asking for the wall "
                "opposite the bed or a better look at the floor area."
            ),
        }
        await self._session_service.create_session(
            app_name=settings.app_name,
            user_id=DEMO_USER_ID,
            session_id=session_id,
            state=initial_state,
        )

        metadata = LiveSessionMetadata(
            session_id=session_id,
            user_id=DEMO_USER_ID,
            created_at=time(),
            status="created",
            snapshot_interval_ms=settings.snapshot_interval_ms,
        )
        self._sessions[session_id] = metadata

        await asyncio.to_thread(
            self._firestore_store.create_live_session,
            session_id=session_id,
            user_id=DEMO_USER_ID,
            app_name=settings.app_name,
            status=metadata.status,
            initial_state=initial_state,
        )
        return metadata

    def session_exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def get_session_context(self, session_id: str) -> dict[str, object]:
        metadata = self._require_session(session_id)
        persisted_session = self._firestore_store.get_live_session(session_id)
        if persisted_session:
            self._merge_persisted_session_context(
                metadata=metadata,
                persisted_session=persisted_session,
            )
        return self._serialize_session_context(metadata)

    def get_persisted_session_context(self, session_id: str) -> dict[str, object]:
        metadata = self._sessions.get(session_id)
        if metadata is not None:
            return self.get_session_context(session_id)

        persisted_session = self._firestore_store.get_live_session(session_id)
        if persisted_session is None:
            raise KeyError(f"Unknown live session `{session_id}`.")

        snapshot_interval_ms = self._read_snapshot_interval_ms(persisted_session)
        latest_snapshot_path = _read_optional_text(
            persisted_session.get("latest_snapshot_path")
        )
        return {
            "session_id": _read_optional_text(
                persisted_session.get("session_id")
            )
            or session_id,
            "status": _read_optional_text(persisted_session.get("status")) or "created",
            "snapshot_interval_ms": snapshot_interval_ms,
            "latest_snapshot_path": latest_snapshot_path,
            "latest_snapshot_timestamp_ms": _read_optional_int(
                persisted_session.get("latest_snapshot_timestamp_ms")
            ),
            "latest_snapshot_available": latest_snapshot_path is not None,
            "snapshot_count": _read_nonnegative_int(
                persisted_session.get("snapshot_count")
            ),
            "flow_state": _read_optional_text(persisted_session.get("flow_state"))
            or "room",
            "awaiting_generation_confirmation": bool(
                persisted_session.get("awaiting_generation_confirmation")
            ),
            "generation_confirmed": bool(
                persisted_session.get("generation_confirmed")
            ),
            "generation_feedback": _read_optional_text(
                persisted_session.get("generation_feedback")
            ),
            "latest_design_brief": _read_optional_text(
                persisted_session.get("latest_design_brief")
            ),
            "latest_inspiration_search_queries": _read_string_list(
                persisted_session.get("latest_inspiration_search_queries")
            ),
            "latest_inspiration_image_results": _read_dict_list(
                persisted_session.get("latest_inspiration_image_results")
            ),
            "room_memory": _read_optional_text(persisted_session.get("room_memory")),
            "vibe_memory": _read_optional_text(persisted_session.get("vibe_memory")),
            "latest_generated_render_path": _read_optional_text(
                persisted_session.get("latest_generated_render_path")
            ),
            "latest_generated_render_mime_type": _read_optional_text(
                persisted_session.get("latest_generated_render_mime_type")
            ),
            "latest_generated_render_available": bool(
                _read_optional_text(persisted_session.get("latest_generated_render_path"))
            ),
            "latest_tool_name": _read_optional_text(
                persisted_session.get("latest_tool_name")
            ),
            "latest_tool_status": _read_optional_text(
                persisted_session.get("latest_tool_status")
            ),
            "latest_tool_detail": _read_optional_text(
                persisted_session.get("latest_tool_detail")
            ),
            "latest_user_transcript": _read_optional_text(
                persisted_session.get("latest_user_transcript")
            ),
            "latest_agent_transcript": _read_optional_text(
                persisted_session.get("latest_agent_transcript")
            ),
        }

    def _serialize_session_context(
        self, metadata: LiveSessionMetadata
    ) -> dict[str, object]:
        return {
            "session_id": metadata.session_id,
            "status": metadata.status,
            "snapshot_interval_ms": metadata.snapshot_interval_ms,
            "latest_snapshot_path": metadata.latest_snapshot_path,
            "latest_snapshot_timestamp_ms": metadata.latest_snapshot_timestamp_ms,
            "latest_snapshot_available": metadata.latest_snapshot_path is not None,
            "snapshot_count": metadata.snapshot_count,
            "flow_state": metadata.flow_state,
            "awaiting_generation_confirmation": (
                metadata.awaiting_generation_confirmation
            ),
            "generation_confirmed": metadata.generation_confirmed,
            "generation_feedback": metadata.generation_feedback,
            "latest_design_brief": metadata.latest_design_brief,
            "latest_inspiration_search_queries": list(
                metadata.latest_inspiration_search_queries
            ),
            "latest_inspiration_image_results": list(
                metadata.latest_inspiration_image_results
            ),
            "room_memory": metadata.room_memory,
            "vibe_memory": metadata.vibe_memory,
            "latest_generated_render_path": metadata.latest_generated_render_path,
            "latest_generated_render_mime_type": metadata.latest_generated_render_mime_type,
            "latest_generated_render_available": (
                metadata.latest_generated_render_path is not None
            ),
            "latest_tool_name": metadata.latest_tool_name,
            "latest_tool_status": metadata.latest_tool_status,
            "latest_tool_detail": metadata.latest_tool_detail,
            "latest_user_transcript": metadata.latest_user_transcript,
            "latest_agent_transcript": metadata.latest_agent_transcript,
        }

    def _merge_persisted_session_context(
        self,
        *,
        metadata: LiveSessionMetadata,
        persisted_session: dict[str, object],
    ) -> None:
        metadata.status = _read_optional_text(persisted_session.get("status")) or (
            metadata.status
        )
        metadata.snapshot_interval_ms = self._read_snapshot_interval_ms(
            persisted_session,
            fallback=metadata.snapshot_interval_ms,
        )
        metadata.latest_snapshot_path = _read_optional_text(
            persisted_session.get("latest_snapshot_path")
        )
        metadata.latest_snapshot_timestamp_ms = _read_optional_int(
            persisted_session.get("latest_snapshot_timestamp_ms")
        )
        metadata.snapshot_count = _read_nonnegative_int(
            persisted_session.get("snapshot_count"),
            fallback=metadata.snapshot_count,
        )
        metadata.flow_state = (
            _read_optional_text(persisted_session.get("flow_state"))
            or metadata.flow_state
        )
        metadata.awaiting_generation_confirmation = bool(
            persisted_session.get("awaiting_generation_confirmation")
        )
        metadata.generation_confirmed = bool(
            persisted_session.get("generation_confirmed")
        )
        metadata.generation_feedback = _read_optional_text(
            persisted_session.get("generation_feedback")
        )
        metadata.latest_design_brief = _read_optional_text(
            persisted_session.get("latest_design_brief")
        )
        metadata.latest_inspiration_search_queries = _read_string_list(
            persisted_session.get("latest_inspiration_search_queries")
        )
        metadata.latest_inspiration_image_results = _read_dict_list(
            persisted_session.get("latest_inspiration_image_results")
        )
        metadata.room_memory = _read_optional_text(persisted_session.get("room_memory"))
        metadata.vibe_memory = _read_optional_text(persisted_session.get("vibe_memory"))
        metadata.latest_generated_render_path = _read_optional_text(
            persisted_session.get("latest_generated_render_path")
        )
        metadata.latest_generated_render_mime_type = _read_optional_text(
            persisted_session.get("latest_generated_render_mime_type")
        )
        metadata.latest_tool_name = _read_optional_text(
            persisted_session.get("latest_tool_name")
        )
        metadata.latest_tool_status = _read_optional_text(
            persisted_session.get("latest_tool_status")
        )
        metadata.latest_tool_detail = _read_optional_text(
            persisted_session.get("latest_tool_detail")
        )
        metadata.latest_user_transcript = _read_optional_text(
            persisted_session.get("latest_user_transcript")
        )
        metadata.latest_agent_transcript = _read_optional_text(
            persisted_session.get("latest_agent_transcript")
        )

    def _read_snapshot_interval_ms(
        self,
        persisted_session: dict[str, object],
        *,
        fallback: int | None = None,
    ) -> int:
        initial_state = persisted_session.get("initial_state")
        snapshot_interval_ms = None
        if isinstance(initial_state, dict):
            snapshot_interval_ms = initial_state.get("snapshot_interval_ms")
        return _read_nonnegative_int(
            snapshot_interval_ms,
            fallback=(
                fallback
                if fallback is not None
                else get_settings().snapshot_interval_ms
            ),
        )

    def build_instruction_context(self, session_id: str) -> str:
        if not session_id or session_id not in self._sessions:
            return (
                "Live context:\n"
                "- No session metadata is loaded yet.\n"
                "- Ask the user to start talking or enable the camera if you need room context."
            )

        metadata = self._sessions[session_id]
        if metadata.latest_snapshot_path:
            snapshot_line = (
                f"- Latest room snapshot is available at {metadata.latest_snapshot_path} "
                f"captured at {metadata.latest_snapshot_timestamp_ms} ms."
            )
        else:
            snapshot_line = (
                "- No room snapshot has been captured yet. Ask the user to point the camera at the room."
            )

        search_plan_line = (
            "- Latest inspiration search plan: "
            + " | ".join(metadata.latest_inspiration_search_queries[:3])
            if metadata.latest_inspiration_search_queries
            else "- No inspiration search plan has been saved yet."
        )
        room_memory_line = (
            "- Room memory saved."
            if metadata.room_memory
            else "- No room memory has been saved yet."
        )
        vibe_memory_line = (
            "- Vibe memory saved."
            if metadata.vibe_memory
            else "- No vibe memory has been saved yet."
        )
        image_result_line = (
            "- Inspiration image matches are saved for the latest search plan."
            if metadata.latest_inspiration_image_results
            else "- No inspiration image matches have been saved yet."
        )
        confirmation_line = (
            "- Waiting for user confirmation before generating the redesign."
            if metadata.awaiting_generation_confirmation
            else "- No pending generation confirmation."
        )
        generated_render_line = (
            "- A redesigned room render has already been generated for this session."
            if metadata.latest_generated_render_path
            else "- No redesigned room render has been generated yet."
        )

        return "\n".join(
            [
                "Live context:",
                f"- Session status: {metadata.status}.",
                "- Persona anchor: a playful but practical interior decorator with strong visual opinions.",
                snapshot_line,
                room_memory_line,
                vibe_memory_line,
                search_plan_line,
                image_result_line,
                confirmation_line,
                generated_render_line,
                "- Camera frames arrive as periodic JPEG snapshots rather than continuous video.",
                "- Guide the scan one move at a time with prompts like 'show me the wall opposite the bed' or 'tilt down toward the floor'.",
                "- When the scan begins, briefly introduce yourself as the decorator and ask for one useful room angle.",
                "- Keep spoken replies short so the user can interrupt naturally.",
            ]
        )

    async def start_live_session(
        self, session_id: str
    ) -> tuple[AsyncGenerator, LiveRequestQueue]:
        metadata = self._require_session(session_id)
        await self.update_session_status(session_id, "connected")
        live_request_queue = LiveRequestQueue()
        if not metadata.primer_sent:
            live_request_queue.send_content(
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part.from_text(
                            text=(
                                "Live session primer: introduce yourself in one short sentence as the room's decorator, "
                                "then ask for one helpful scan angle such as a wide shot of the room or the wall opposite the bed. "
                                "Keep the reply interruption-friendly and voice-first."
                            )
                        )
                    ],
                )
            )
            metadata.primer_sent = True
        live_events = self.runner.run_live(
            user_id=metadata.user_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=self._build_run_config(),
        )
        return live_events, live_request_queue

    async def forward_events_to_websocket(
        self,
        *,
        websocket: WebSocket,
        live_events: AsyncGenerator,
        session_id: str,
    ) -> None:
        metadata = self._require_session(session_id)
        async for event in live_events:
            if event.error_message:
                await _send_ws_json(
                    websocket=websocket,
                    session_id=session_id,
                    dedupe_cache=metadata.last_websocket_payload_fingerprints,
                    payload={
                        "type": "status",
                        "state": "error",
                        "detail": event.error_message,
                    },
                )
                continue

            if event.input_transcription:
                await self._handle_input_transcription(
                    websocket=websocket,
                    session_id=session_id,
                    transcription=event.input_transcription,
                )

            if event.output_transcription:
                await self._handle_output_transcription(
                    websocket=websocket,
                    session_id=session_id,
                    transcription=event.output_transcription,
                    interrupted=bool(event.interrupted),
                )

            if event.content and event.content.parts:
                final_text_parts: list[str] = []
                for part in event.content.parts:
                    if (
                        part.inline_data
                        and (part.inline_data.mime_type or "").startswith("audio/pcm")
                    ):
                        await _send_ws_json(
                            websocket=websocket,
                            session_id=session_id,
                            dedupe_cache=metadata.last_websocket_payload_fingerprints,
                            payload={
                                "type": "audio",
                                "mime_type": part.inline_data.mime_type,
                                "data": base64.b64encode(part.inline_data.data).decode(
                                    "ascii"
                                ),
                            },
                        )
                    elif part.text and event.partial and not event.output_transcription:
                        await _send_ws_json(
                            websocket=websocket,
                            session_id=session_id,
                            dedupe_cache=metadata.last_websocket_payload_fingerprints,
                            payload={"type": "partial_text", "text": part.text},
                        )
                    elif (
                        part.text
                        and event.partial is not True
                        and not event.output_transcription
                    ):
                        final_text_parts.append(part.text)

                if final_text_parts:
                    await _send_ws_json(
                        websocket=websocket,
                        session_id=session_id,
                        dedupe_cache=metadata.last_websocket_payload_fingerprints,
                        payload={
                            "type": "agent_text",
                            "text": "".join(final_text_parts),
                        },
                    )
                    await self.record_agent_turn(
                        session_id=session_id,
                        text="".join(final_text_parts),
                        interrupted=bool(event.interrupted),
                    )

            if event.turn_complete or event.interrupted:
                if event.interrupted:
                    await self.record_interrupt(
                        session_id=session_id, source="live_api"
                    )
                await _send_ws_json(
                    websocket=websocket,
                    session_id=session_id,
                    dedupe_cache=metadata.last_websocket_payload_fingerprints,
                    payload={
                        "type": "turn_state",
                        "turn_complete": bool(event.turn_complete),
                        "interrupted": bool(event.interrupted),
                    },
                )

    async def save_snapshot(
        self,
        *,
        session_id: str,
        image_bytes: bytes,
        timestamp_ms: int,
    ) -> dict[str, object]:
        metadata = self._require_session(session_id)
        snapshot_details = await asyncio.to_thread(
            self._storage_store.save_session_snapshot,
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            image_bytes=image_bytes,
        )
        metadata.latest_snapshot_path = str(snapshot_details["object_path"])
        metadata.latest_snapshot_timestamp_ms = timestamp_ms
        metadata.snapshot_count += 1

        await asyncio.to_thread(
            self._firestore_store.update_live_session,
            session_id,
            latest_snapshot_path=metadata.latest_snapshot_path,
            latest_snapshot_timestamp_ms=timestamp_ms,
            snapshot_count=metadata.snapshot_count,
        )
        await asyncio.to_thread(
            self._firestore_store.append_live_event,
            session_id=session_id,
            event_type="snapshot_received",
            payload={
                "object_path": metadata.latest_snapshot_path,
                "timestamp_ms": timestamp_ms,
                "snapshot_count": metadata.snapshot_count,
            },
        )
        return snapshot_details

    async def update_session_status(
        self,
        session_id: str,
        status: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        metadata = self._require_session(session_id)
        metadata.status = status
        payload = {"status": status}
        if detail:
            payload["detail"] = detail
        await asyncio.to_thread(
            self._firestore_store.update_live_session, session_id, **payload
        )

    async def record_user_turn(
        self, *, session_id: str, text: str, source: str
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        metadata = self._require_session(session_id)
        metadata.latest_user_transcript = cleaned
        await asyncio.to_thread(
            self._firestore_store.append_live_event,
            session_id=session_id,
            event_type="user_turn",
            payload={"text": cleaned, "source": source},
        )
        await asyncio.to_thread(
            self._firestore_store.update_live_session,
            session_id,
            latest_user_transcript=cleaned,
        )

    async def record_agent_turn(
        self, *, session_id: str, text: str, interrupted: bool
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        metadata = self._require_session(session_id)
        metadata.latest_agent_transcript = cleaned
        await asyncio.to_thread(
            self._firestore_store.append_live_event,
            session_id=session_id,
            event_type="agent_turn",
            payload={"text": cleaned, "interrupted": interrupted},
        )
        await asyncio.to_thread(
            self._firestore_store.update_live_session,
            session_id,
            latest_agent_transcript=cleaned,
        )

    async def record_interrupt(self, *, session_id: str, source: str) -> None:
        await asyncio.to_thread(
            self._firestore_store.append_live_event,
            session_id=session_id,
            event_type="interrupt",
            payload={"source": source},
        )

    def record_tool_activity(
        self,
        *,
        session_id: str,
        tool_name: str,
        status: str,
        detail: str,
    ) -> dict[str, object]:
        metadata = self._require_session(session_id)
        metadata.latest_tool_name = tool_name
        metadata.latest_tool_status = status
        metadata.latest_tool_detail = detail
        log_level = logging.INFO
        if status == "failed":
            log_level = logging.WARNING
        logger.log(
            log_level,
            "[tool][session=%s][%s] %s - %s",
            session_id,
            status,
            tool_name,
            detail,
        )
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="tool_activity",
            payload={
                "tool_name": tool_name,
                "status": status,
                "detail": detail,
            },
        )
        self._firestore_store.update_live_session(
            session_id,
            latest_tool_name=tool_name,
            latest_tool_status=status,
            latest_tool_detail=detail,
        )
        return self.get_session_context(session_id)

    def set_flow_state(self, *, session_id: str, flow_state: str) -> dict[str, object]:
        cleaned_state = flow_state.strip()
        if not cleaned_state:
            raise ValueError("Flow state must not be empty.")

        metadata = self._require_session(session_id)
        metadata.flow_state = cleaned_state
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="flow_state_updated",
            payload={"flow_state": cleaned_state},
        )
        self._firestore_store.update_live_session(
            session_id,
            flow_state=cleaned_state,
        )
        return self.get_session_context(session_id)

    def set_generation_confirmation(
        self,
        *,
        session_id: str,
        confirmed: bool,
        feedback: str | None = None,
        awaiting_confirmation: bool | None = None,
    ) -> dict[str, object]:
        metadata = self._require_session(session_id)
        cleaned_feedback = _read_optional_text(feedback)
        metadata.generation_confirmed = bool(confirmed)
        metadata.generation_feedback = cleaned_feedback
        if awaiting_confirmation is not None:
            metadata.awaiting_generation_confirmation = bool(awaiting_confirmation)
        else:
            metadata.awaiting_generation_confirmation = False

        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="generation_confirmation_saved",
            payload={
                "confirmed": metadata.generation_confirmed,
                "feedback": cleaned_feedback,
            },
        )
        self._firestore_store.update_live_session(
            session_id,
            generation_confirmed=metadata.generation_confirmed,
            generation_feedback=metadata.generation_feedback,
            awaiting_generation_confirmation=metadata.awaiting_generation_confirmation,
        )
        return self.get_session_context(session_id)

    def save_room_memory(
        self,
        *,
        session_id: str,
        room_memory: str,
    ) -> dict[str, object]:
        cleaned_memory = room_memory.strip()
        if not cleaned_memory:
            raise ValueError("Room memory must not be empty.")

        metadata = self._require_session(session_id)
        metadata.room_memory = cleaned_memory
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="room_memory_saved",
            payload={"room_memory": cleaned_memory},
        )
        self._firestore_store.update_live_session(
            session_id,
            room_memory=cleaned_memory,
        )
        return self.get_session_context(session_id)

    def save_vibe_memory(
        self,
        *,
        session_id: str,
        vibe_memory: str,
    ) -> dict[str, object]:
        cleaned_memory = vibe_memory.strip()
        if not cleaned_memory:
            raise ValueError("Vibe memory must not be empty.")

        metadata = self._require_session(session_id)
        metadata.vibe_memory = cleaned_memory
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="vibe_memory_saved",
            payload={"vibe_memory": cleaned_memory},
        )
        self._firestore_store.update_live_session(
            session_id,
            vibe_memory=cleaned_memory,
        )
        return self.get_session_context(session_id)

    def save_inspiration_search_plan(
        self,
        *,
        session_id: str,
        user_query: str,
        search_queries: list[str],
    ) -> dict[str, object]:
        cleaned_query = user_query.strip()
        cleaned_queries = [query.strip() for query in search_queries if query.strip()]

        if not cleaned_query:
            raise ValueError("User query must not be empty.")

        if not cleaned_queries:
            raise ValueError("Search queries must not be empty.")

        metadata = self._require_session(session_id)
        metadata.latest_design_brief = cleaned_query
        metadata.latest_inspiration_search_queries = cleaned_queries
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="inspiration_search_plan_saved",
            payload={
                "user_query": cleaned_query,
                "search_queries": cleaned_queries,
            },
        )
        self._firestore_store.update_live_session(
            session_id,
            latest_design_brief=cleaned_query,
            latest_inspiration_search_queries=list(cleaned_queries),
        )
        return self.get_session_context(session_id)

    def save_inspiration_image_results(
        self,
        *,
        session_id: str,
        image_results_by_query: list[dict[str, object]],
    ) -> dict[str, object]:
        if not image_results_by_query:
            raise ValueError("Image search results must not be empty.")

        metadata = self._require_session(session_id)
        metadata.latest_inspiration_image_results = image_results_by_query
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="inspiration_image_results_saved",
            payload={
                "query_count": len(image_results_by_query),
                "results_by_query": image_results_by_query,
            },
        )
        self._firestore_store.update_live_session(
            session_id,
            latest_inspiration_image_results=image_results_by_query,
        )
        return self.get_session_context(session_id)

    def save_generated_render(
        self,
        *,
        session_id: str,
        render_details: dict[str, object],
        model_name: str,
        prompt_summary: str,
    ) -> dict[str, object]:
        object_path = str(render_details.get("object_path", "")).strip()
        content_type = str(render_details.get("content_type", "")).strip()
        if not object_path:
            raise ValueError("Generated render object path must not be empty.")

        metadata = self._require_session(session_id)
        metadata.latest_generated_render_path = object_path
        metadata.latest_generated_render_mime_type = content_type or None
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="generated_render_saved",
            payload={
                "object_path": object_path,
                "content_type": content_type,
                "model_name": model_name.strip(),
                "prompt_summary": prompt_summary.strip(),
            },
        )
        self._firestore_store.update_live_session(
            session_id,
            latest_generated_render_path=metadata.latest_generated_render_path,
            latest_generated_render_mime_type=metadata.latest_generated_render_mime_type,
        )
        return self.get_session_context(session_id)

    def _build_run_config(self) -> RunConfig:
        settings = get_settings()
        voice_config = genai_types.VoiceConfig(
            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                voice_name=settings.live_agent_voice
            )
        )
        speech_config = genai_types.SpeechConfig(
            voice_config=voice_config,
            language_code=settings.live_agent_language_code,
        )
        realtime_input_config = genai_types.RealtimeInputConfig(
            automatic_activity_detection=genai_types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=(
                    genai_types.StartSensitivity.START_SENSITIVITY_LOW
                ),
                end_of_speech_sensitivity=(
                    genai_types.EndSensitivity.END_SENSITIVITY_LOW
                ),
                prefix_padding_ms=100,
                silence_duration_ms=800,
            ),
            activity_handling=(
                genai_types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
            ),
            turn_coverage=genai_types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
        )
        run_config = RunConfig(
            speech_config=speech_config,
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
            realtime_input_config=realtime_input_config,
            tool_thread_pool_config=ToolThreadPoolConfig(max_workers=4),
        )
        # Assign after initialization so ADK preserves the enum instead of
        # coercing it to a plain string, which avoids noisy serializer warnings.
        run_config.response_modalities = [genai_types.Modality.AUDIO]
        return run_config

    async def _handle_input_transcription(
        self,
        *,
        websocket: WebSocket,
        session_id: str,
        transcription: genai_types.Transcription,
    ) -> None:
        if transcription.finished:
            await self.record_user_turn(
                session_id=session_id,
                text=transcription.text,
                source="audio_transcription",
            )
            await websocket.send_json(
                {
                    "type": "status",
                    "state": "user_transcript",
                    "detail": transcription.text,
                }
            )
            return

        if transcription.text:
            await websocket.send_json(
                {
                    "type": "status",
                    "state": "listening",
                    "detail": transcription.text,
                }
            )

    async def _handle_output_transcription(
        self,
        *,
        websocket: WebSocket,
        session_id: str,
        transcription: genai_types.Transcription,
        interrupted: bool,
    ) -> None:
        if transcription.finished:
            await websocket.send_json(
                {"type": "agent_text", "text": transcription.text}
            )
            await self.record_agent_turn(
                session_id=session_id,
                text=transcription.text,
                interrupted=interrupted,
            )
            return

        if transcription.text:
            await websocket.send_json(
                {"type": "partial_text", "text": transcription.text}
            )

    def _require_session(self, session_id: str) -> LiveSessionMetadata:
        metadata = self._sessions.get(session_id)
        if metadata is None:
            raise KeyError(f"Unknown live session `{session_id}`.")
        return metadata


@lru_cache(maxsize=1)
def get_live_runtime_manager() -> LiveRuntimeManager:
    return LiveRuntimeManager()


def _read_optional_text(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _read_optional_int(value: object) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_nonnegative_int(value: object, fallback: int = 0) -> int:
    parsed = _read_optional_int(value)
    if parsed is None:
        return fallback
    return max(0, parsed)


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    cleaned_values: list[str] = []
    for item in value:
        text = _read_optional_text(item)
        if text is not None:
            cleaned_values.append(text)
    return cleaned_values


def _read_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]
