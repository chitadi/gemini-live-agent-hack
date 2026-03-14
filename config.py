import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)


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


@dataclass(frozen=True)
class Settings:
    app_name: str
    google_genai_use_vertexai: bool
    google_cloud_project: str
    google_cloud_location: str
    firestore_database: str
    gcs_bucket_name: str
    adk_live_model: str
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
        adk_live_model=os.getenv("ADK_LIVE_MODEL", "gemini-2.5-flash-live-001"),
        port=int(os.getenv("PORT", "8080")),
    )

    if not settings.google_genai_use_vertexai:
        raise ValueError(
            "Phase 0 is Vertex-first. Set GOOGLE_GENAI_USE_VERTEXAI=TRUE."
        )

    return settings
