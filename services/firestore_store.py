from typing import Any

from functools import lru_cache

from google.cloud import firestore

from config import get_settings


class FirestoreStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.project_id = settings.google_cloud_project
        self.database = settings.firestore_database
        self.client = firestore.Client(
            project=self.project_id,
            database=self.database,
        )

    def healthcheck(self) -> dict[str, object]:
        list(self.client.collection("_runtime_health").limit(1).stream())
        return {
            "status": "ok",
            "project_id": self.project_id,
            "database": self.database,
        }

    def create_live_session(
        self,
        *,
        session_id: str,
        user_id: str,
        app_name: str,
        status: str,
        initial_state: dict[str, Any],
    ) -> None:
        self._live_session_doc(session_id).set(
            {
                "session_id": session_id,
                "user_id": user_id,
                "app_name": app_name,
                "status": status,
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "latest_snapshot_path": None,
                "latest_snapshot_timestamp_ms": None,
                "initial_state": initial_state,
            },
            merge=True,
        )

    def update_live_session(
        self, session_id: str, **fields: Any
    ) -> None:
        payload = {
            **fields,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        self._live_session_doc(session_id).set(payload, merge=True)

    def append_live_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._live_session_doc(session_id).collection("events").document().set(
            {
                "type": event_type,
                "payload": payload or {},
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )

    def _live_session_doc(self, session_id: str):
        return self.client.collection("live_sessions").document(session_id)


@lru_cache(maxsize=1)
def get_firestore_store() -> FirestoreStore:
    return FirestoreStore()
