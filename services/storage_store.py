import mimetypes
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

    def list_session_snapshots(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            return []

        prefix = f"sessions/{session_id}/snapshots/"
        blobs = sorted(
            self.client.list_blobs(self.bucket_name, prefix=prefix),
            key=lambda blob: blob.name,
            reverse=True,
        )
        snapshots: list[dict[str, object]] = []
        for blob in blobs[:limit]:
            snapshots.append(
                {
                    "bucket": self.bucket_name,
                    "object_path": blob.name,
                    "gs_uri": f"gs://{self.bucket_name}/{blob.name}",
                    "content_type": blob.content_type or "image/jpeg",
                    "size_bytes": blob.size or 0,
                }
            )
        return snapshots

    def save_generated_render(
        self,
        *,
        session_id: str,
        timestamp_ms: int,
        image_bytes: bytes,
        content_type: str,
    ) -> dict[str, object]:
        if not image_bytes:
            raise ValueError("Generated render payload was empty.")

        extension = _extension_for_content_type(content_type)
        object_path = f"sessions/{session_id}/renders/{timestamp_ms}{extension}"
        blob = self.client.bucket(self.bucket_name).blob(object_path)
        blob.upload_from_string(image_bytes, content_type=content_type)

        return {
            "bucket": self.bucket_name,
            "object_path": object_path,
            "gs_uri": f"gs://{self.bucket_name}/{object_path}",
            "content_type": content_type,
            "size_bytes": len(image_bytes),
        }

    def download_object(self, object_path: str) -> dict[str, object]:
        cleaned_path = object_path.strip()
        if not cleaned_path:
            raise ValueError("Object path must not be empty.")

        blob = self.client.bucket(self.bucket_name).blob(cleaned_path)
        if not blob.exists():
            raise FileNotFoundError(f"Cloud Storage object `{cleaned_path}` was not found.")

        return {
            "bucket": self.bucket_name,
            "object_path": cleaned_path,
            "content_type": blob.content_type or _guess_content_type(cleaned_path),
            "data": blob.download_as_bytes(),
            "size_bytes": blob.size or 0,
            "gs_uri": f"gs://{self.bucket_name}/{cleaned_path}",
        }


@lru_cache(maxsize=1)
def get_storage_store() -> StorageStore:
    return StorageStore()


def _extension_for_content_type(content_type: str) -> str:
    guessed_extension = mimetypes.guess_extension(content_type.strip()) or ""
    if guessed_extension:
        return guessed_extension
    return ".png"


def _guess_content_type(object_path: str) -> str:
    guessed_type, _ = mimetypes.guess_type(object_path)
    return guessed_type or "application/octet-stream"
