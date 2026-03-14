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


@lru_cache(maxsize=1)
def get_storage_store() -> StorageStore:
    return StorageStore()
