from __future__ import annotations

import asyncio
import base64
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
MAX_RECENT_OBSERVATIONS = 5


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
    recent_observations: list[str] = field(default_factory=list)
    latest_user_transcript: str | None = None
    latest_agent_transcript: str | None = None
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
        return {
            "session_id": metadata.session_id,
            "status": metadata.status,
            "snapshot_interval_ms": metadata.snapshot_interval_ms,
            "latest_snapshot_path": metadata.latest_snapshot_path,
            "latest_snapshot_timestamp_ms": metadata.latest_snapshot_timestamp_ms,
            "latest_snapshot_available": metadata.latest_snapshot_path is not None,
            "snapshot_count": metadata.snapshot_count,
            "recent_observations": list(metadata.recent_observations),
            "latest_user_transcript": metadata.latest_user_transcript,
            "latest_agent_transcript": metadata.latest_agent_transcript,
        }

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

        observations = metadata.recent_observations[-3:]
        observation_line = (
            "- Saved scan observations: " + " | ".join(observations)
            if observations
            else "- No scan observations have been saved yet."
        )

        return "\n".join(
            [
                "Live context:",
                f"- Session status: {metadata.status}.",
                "- Persona anchor: a playful but practical interior decorator with strong visual opinions.",
                snapshot_line,
                observation_line,
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
        async for event in live_events:
            if event.error_message:
                await websocket.send_json(
                    {
                        "type": "status",
                        "state": "error",
                        "detail": event.error_message,
                    }
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
                        await websocket.send_json(
                            {
                                "type": "audio",
                                "mime_type": part.inline_data.mime_type,
                                "data": base64.b64encode(part.inline_data.data).decode(
                                    "ascii"
                                ),
                            }
                        )
                    elif part.text and event.partial and not event.output_transcription:
                        await websocket.send_json(
                            {"type": "partial_text", "text": part.text}
                        )
                    elif (
                        part.text
                        and event.partial is not True
                        and not event.output_transcription
                    ):
                        final_text_parts.append(part.text)

                if final_text_parts:
                    await websocket.send_json(
                        {
                            "type": "agent_text",
                            "text": "".join(final_text_parts),
                        }
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
                await websocket.send_json(
                    {
                        "type": "turn_state",
                        "turn_complete": bool(event.turn_complete),
                        "interrupted": bool(event.interrupted),
                    }
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

    def persist_snapshot_observation(self, *, session_id: str, note: str) -> dict[str, object]:
        cleaned = note.strip()
        if not cleaned:
            raise ValueError("Observation note must not be empty.")

        metadata = self._require_session(session_id)
        metadata.recent_observations.append(cleaned)
        metadata.recent_observations = metadata.recent_observations[
            -MAX_RECENT_OBSERVATIONS:
        ]
        self._firestore_store.append_live_event(
            session_id=session_id,
            event_type="agent_observation",
            payload={"note": cleaned},
        )
        self._firestore_store.update_live_session(
            session_id,
            recent_observations=list(metadata.recent_observations),
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
        return RunConfig(
            response_modalities=[
                genai_types.Modality.AUDIO,
            ],
            speech_config=speech_config,
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
            tool_thread_pool_config=ToolThreadPoolConfig(max_workers=4),
        )

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
