import asyncio
import base64
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError
from google.genai import types as genai_types

from config import get_settings
from services.firestore_store import get_firestore_store
from services.live_runtime import get_live_runtime_manager
from services.storage_store import get_storage_store


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")


def _build_bootstrap_report() -> dict[str, object]:
    settings = get_settings()

    try:
        credentials, detected_project = google_auth_default()
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Application Default Credentials are not configured. "
            "Run `gcloud auth application-default login`."
        ) from exc

    firestore_status = get_firestore_store().healthcheck()
    storage_status = get_storage_store().healthcheck()

    return {
        "app_name": settings.app_name,
        "project_id": settings.google_cloud_project,
        "detected_project_id": detected_project,
        "region": settings.google_cloud_location,
        "firestore": firestore_status,
        "storage": storage_status,
        "credentials_type": credentials.__class__.__name__,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_report = _build_bootstrap_report()
    app.state.bootstrap_report = bootstrap_report
    logger.info(
        "Phase 1 live runtime validated for project %s",
        bootstrap_report["project_id"],
    )
    yield


app = FastAPI(
    title="Gemini Live Agent Hack",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "phase": "phase1",
        "status": "ready",
        "backend": "vertex-ai",
        "project": settings.google_cloud_project,
        "region": settings.google_cloud_location,
        "bucket": settings.gcs_bucket_name,
        "firestore_database": settings.firestore_database,
        "model": settings.adk_live_model,
    }


@app.get("/healthz")
def healthz() -> dict[str, object]:
    try:
        report = _build_bootstrap_report()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "ok",
        "checks": report,
    }


@app.get("/config")
def config_view() -> dict[str, object]:
    return {
        "config": get_settings().public_dict(),
    }


@app.get("/demo")
def demo_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "demo.html")


@app.post("/api/live/session")
async def create_live_session(request: Request) -> dict[str, object]:
    session = await get_live_runtime_manager().create_session()
    return {
        "session_id": session.session_id,
        "websocket_url": _build_websocket_url(
            request=request, session_id=session.session_id
        ),
        "snapshot_interval_ms": session.snapshot_interval_ms,
    }


@app.websocket("/api/live/ws/{session_id}", name="live_ws")
async def live_ws(websocket: WebSocket, session_id: str) -> None:
    manager = get_live_runtime_manager()
    if not manager.session_exists(session_id):
        await websocket.close(code=4404, reason="Unknown live session.")
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "status",
            "state": "connected",
            "detail": "Live session ready. Use the mic or camera to start the room scan.",
        }
    )

    live_events, live_request_queue = await manager.start_live_session(session_id)
    forward_task = asyncio.create_task(
        manager.forward_events_to_websocket(
            websocket=websocket,
            live_events=live_events,
            session_id=session_id,
        )
    )
    user_audio_active = False
    final_status = "completed"

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await websocket.send_json(
                    {
                        "type": "status",
                        "state": "invalid_message",
                        "detail": "Expected an object payload.",
                    }
                )
                continue

            message_type = str(payload.get("type", "")).strip()
            if message_type == "text":
                text = str(payload.get("text", "")).strip()
                if not text:
                    continue
                live_request_queue.send_content(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part.from_text(text=text)],
                    )
                )
                await manager.record_user_turn(
                    session_id=session_id, text=text, source="text"
                )
                continue

            if message_type == "audio":
                audio_bytes = _decode_b64_payload(payload.get("data"))
                if audio_bytes is None:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "state": "invalid_audio",
                            "detail": "Audio payload was not valid base64.",
                        }
                    )
                    continue
                if not user_audio_active:
                    live_request_queue.send_activity_start()
                    user_audio_active = True
                live_request_queue.send_realtime(
                    genai_types.Blob(
                        data=audio_bytes,
                        mime_type=str(payload.get("mime_type", "audio/pcm")),
                    )
                )
                continue

            if message_type == "snapshot":
                image_bytes = _decode_b64_payload(payload.get("data"))
                if image_bytes is None:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "state": "invalid_snapshot",
                            "detail": "Snapshot payload was not valid base64.",
                        }
                    )
                    continue
                timestamp_ms = int(payload.get("timestamp_ms", 0) or 0)
                snapshot_details = await manager.save_snapshot(
                    session_id=session_id,
                    image_bytes=image_bytes,
                    timestamp_ms=timestamp_ms,
                )
                live_request_queue.send_realtime(
                    genai_types.Blob(
                        data=image_bytes,
                        mime_type=str(payload.get("mime_type", "image/jpeg")),
                    )
                )
                await websocket.send_json(
                    {
                        "type": "status",
                        "state": "snapshot_saved",
                        "detail": snapshot_details["object_path"],
                    }
                )
                continue

            if message_type == "interrupt":
                live_request_queue.send_activity_start()
                live_request_queue.send_activity_end()
                user_audio_active = False
                await manager.record_interrupt(
                    session_id=session_id, source="client_button"
                )
                await websocket.send_json(
                    {
                        "type": "status",
                        "state": "interrupt_sent",
                        "detail": "Interrupt signal sent to the live agent.",
                    }
                )
                continue

            if message_type == "end_turn":
                if user_audio_active:
                    live_request_queue.send_activity_end()
                    user_audio_active = False
                await websocket.send_json(
                    {
                        "type": "status",
                        "state": "turn_closed",
                        "detail": "User turn closed.",
                    }
                )
                continue

            await websocket.send_json(
                {
                    "type": "status",
                    "state": "unsupported_message",
                    "detail": f"Unsupported message type `{message_type}`.",
                }
            )
    except WebSocketDisconnect:
        logger.info("Live websocket disconnected for session %s", session_id)
    except Exception as exc:
        logger.exception("Live websocket failed for session %s", session_id)
        final_status = "errored"
        await manager.update_session_status(
            session_id, "errored", detail={"error": str(exc)}
        )
        try:
            await websocket.send_json(
                {"type": "status", "state": "error", "detail": str(exc)}
            )
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if user_audio_active:
            live_request_queue.send_activity_end()
        live_request_queue.close()
        forward_task.cancel()
        try:
            await forward_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Live event forwarder failed for session %s", session_id)
            final_status = "errored"
        try:
            await manager.update_session_status(session_id, final_status)
        except Exception:
            logger.exception("Failed to finalize live session %s", session_id)


def _build_websocket_url(request: Request, session_id: str) -> str:
    websocket_url = str(request.url_for("live_ws", session_id=session_id))
    if websocket_url.startswith("http://"):
        return "ws://" + websocket_url.removeprefix("http://")
    if websocket_url.startswith("https://"):
        return "wss://" + websocket_url.removeprefix("https://")
    return websocket_url


def _decode_b64_payload(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return base64.b64decode(value)
    except Exception:
        return None
