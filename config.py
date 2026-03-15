import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _read_optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _read_optional_any(*names: str) -> str | None:
    for name in names:
        value = _read_optional(name)
        if value:
            return value
    return None


@dataclass(frozen=True)
class Settings:
    app_name: str
    google_genai_use_vertexai: bool
    google_cloud_project: str
    google_cloud_location: str
    firestore_database: str
    gcs_bucket_name: str
    adk_live_model: str
    live_agent_voice: str
    live_agent_language_code: str
    vertex_ai_search_app_id: str | None
    vertex_ai_search_location: str
    vertex_ai_search_serving_config_id: str
    inspiration_image_results_per_query: int
    snapshot_interval_ms: int
    port: int

    def public_dict(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "google_genai_use_vertexai": self.google_genai_use_vertexai,
            "google_cloud_project": self.google_cloud_project,
            "google_cloud_location": self.google_cloud_location,
            "firestore_database": self.firestore_database,
            "gcs_bucket_name": self.gcs_bucket_name,
            "adk_live_model": self.adk_live_model,
            "live_agent_voice": self.live_agent_voice,
            "live_agent_language_code": self.live_agent_language_code,
            "vertex_ai_search_configured": bool(
                self.vertex_ai_search_app_id
            ),
            "vertex_ai_search_location": self.vertex_ai_search_location,
            "vertex_ai_search_serving_config_id": (
                self.vertex_ai_search_serving_config_id
            ),
            "inspiration_image_results_per_query": (
                self.inspiration_image_results_per_query
            ),
            "snapshot_interval_ms": self.snapshot_interval_ms,
            "port": self.port,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        app_name=os.getenv("APP_NAME", "gemini-live-agent-hack"),
        google_genai_use_vertexai=_read_bool("GOOGLE_GENAI_USE_VERTEXAI", True),
        google_cloud_project=_read_required("GOOGLE_CLOUD_PROJECT"),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        gcs_bucket_name=_read_required("GCS_BUCKET_NAME"),
        adk_live_model=os.getenv(
            "ADK_LIVE_MODEL", "gemini-live-2.5-flash-native-audio"
        ),
        live_agent_voice=os.getenv("LIVE_AGENT_VOICE", "Aoede"),
        live_agent_language_code=os.getenv("LIVE_AGENT_LANGUAGE_CODE", "en-US"),
        vertex_ai_search_app_id=_read_optional_any(
            "VERTEX_AI_SEARCH_APP_ID",
            "VERTEX_AI_SEARCH_ENGINE_ID",
            "DISCOVERY_ENGINE_APP_ID",
        ),
        vertex_ai_search_location=os.getenv("VERTEX_AI_SEARCH_LOCATION", "global"),
        vertex_ai_search_serving_config_id=os.getenv(
            "VERTEX_AI_SEARCH_SERVING_CONFIG_ID", "default_search"
        ),
        inspiration_image_results_per_query=int(
            os.getenv("INSPIRATION_IMAGE_RESULTS_PER_QUERY", "3")
        ),
        snapshot_interval_ms=int(os.getenv("SNAPSHOT_INTERVAL_MS", "2500")),
        port=int(os.getenv("PORT", "8080")),
    )

    if not settings.google_genai_use_vertexai:
        raise ValueError(
            "This live runtime is Vertex-first. Set GOOGLE_GENAI_USE_VERTEXAI=TRUE."
        )

    return settings
