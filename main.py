import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError

from config import get_settings
from services.firestore_store import get_firestore_store
from services.storage_store import get_storage_store


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    logger.info("Phase 0 runtime validated for project %s", bootstrap_report["project_id"])
    yield


app = FastAPI(
    title="Gemini Live Agent Hack",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
def root() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "phase": "phase0",
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
