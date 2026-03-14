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
        list(self.client.collection("_phase0_health").limit(1).stream())
        return {
            "status": "ok",
            "project_id": self.project_id,
            "database": self.database,
        }


@lru_cache(maxsize=1)
def get_firestore_store() -> FirestoreStore:
    return FirestoreStore()
