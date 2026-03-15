from functools import lru_cache

from google.cloud import storage

from config import get_settings


class StorageStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.project_id = settings.google_cloud_project
        self.bucket_name = settings.gcs_bucket_name
        self.client = storage.Client(project=self.project_id)

    def healthcheck(self) -> dict[str, object]:
        bucket = self.client.lookup_bucket(self.bucket_name)
        if bucket is None:
            raise RuntimeError(
                f"Cloud Storage bucket `{self.bucket_name}` was not found."
            )

        return {
            "status": "ok",
            "project_id": self.project_id,
            "bucket": self.bucket_name,
            "location": bucket.location,
        }

    def save_session_snapshot(
        self,
        *,
        session_id: str,
        timestamp_ms: int,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> dict[str, object]:
        if not image_bytes:
            raise ValueError("Snapshot payload was empty.")

        object_path = f"sessions/{session_id}/snapshots/{timestamp_ms}.jpg"
        blob = self.client.bucket(self.bucket_name).blob(object_path)
        blob.upload_from_string(image_bytes, content_type=content_type)

        return {
            "bucket": self.bucket_name,
            "object_path": object_path,
            "gs_uri": f"gs://{self.bucket_name}/{object_path}",
            "content_type": content_type,
            "size_bytes": len(image_bytes),
        }


@lru_cache(maxsize=1)
def get_storage_store() -> StorageStore:
    return StorageStore()
