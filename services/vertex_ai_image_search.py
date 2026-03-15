from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request as GoogleAuthRequest

from config import get_settings


_VERTEX_AI_SEARCH_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class _VertexAiSearchHTTPError(RuntimeError):
    def __init__(self, *, code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class VertexAiImageSearchService:
    BASE_URL = "https://discoveryengine.googleapis.com/v1"
    MAX_RESULTS_PER_QUERY = 10

    def __init__(self) -> None:
        settings = get_settings()
        self.project_id = settings.google_cloud_project
        self.location = settings.vertex_ai_search_location
        self.app_id = settings.vertex_ai_search_app_id
        self.serving_config_id = settings.vertex_ai_search_serving_config_id

    def is_configured(self) -> bool:
        return bool(self.app_id)

    def search_images(
        self,
        *,
        query: str,
        results_per_query: int,
    ) -> list[dict[str, object]]:
        if not self.is_configured():
            raise RuntimeError(
                "Vertex AI Search is not configured. Set VERTEX_AI_SEARCH_APP_ID. "
                "VERTEX_AI_SEARCH_LOCATION defaults to global."
            )

        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Search query must not be empty.")

        response = self._request_json(
            query=cleaned_query,
            results_per_query=max(1, min(results_per_query, self.MAX_RESULTS_PER_QUERY)),
        )
        items = response.get("results", [])
        if not isinstance(items, list):
            return []

        return [
            self._normalize_result(item, cleaned_query, index)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]

    def _request_json(
        self,
        *,
        query: str,
        results_per_query: int,
    ) -> dict[str, Any]:
        credentials = self._get_credentials()
        last_http_error: _VertexAiSearchHTTPError | None = None

        for serving_config_id in self._serving_config_candidates():
            for params in self._params_candidates():
                try:
                    return self._perform_request(
                        credentials=credentials,
                        payload={
                            "servingConfig": self._serving_config_path(serving_config_id),
                            "query": query,
                            "pageSize": results_per_query,
                            "offset": 0,
                            "params": params,
                        },
                        serving_config_id=serving_config_id,
                    )
                except _VertexAiSearchHTTPError as exc:
                    last_http_error = exc
                    if exc.code not in {400, 404}:
                        raise RuntimeError(
                            f"Vertex AI Search request failed with HTTP {exc.code}: {exc.detail}"
                        ) from exc
                    continue
                except URLError as exc:
                    raise RuntimeError(
                        f"Vertex AI Search request failed: {exc.reason}"
                    ) from exc

        if last_http_error is not None:
            raise RuntimeError(
                f"Vertex AI Search request failed with HTTP {last_http_error.code}: "
                f"{last_http_error.detail}"
            ) from last_http_error

        raise RuntimeError("Vertex AI Search request failed before any request was sent.")

    def _perform_request(
        self,
        *,
        credentials: Any,
        payload: dict[str, Any],
        serving_config_id: str,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self._endpoint_url(serving_config_id),
            data=body,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
                "X-Goog-User-Project": self.project_id,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=20) as response:
                payload_text = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise _VertexAiSearchHTTPError(code=exc.code, detail=detail) from exc

        parsed = json.loads(payload_text)
        if not isinstance(parsed, dict):
            raise RuntimeError("Vertex AI Search returned an invalid payload.")
        return parsed

    def _get_credentials(self) -> Any:
        try:
            credentials, _ = google_auth_default(scopes=[_VERTEX_AI_SEARCH_SCOPE])
        except DefaultCredentialsError as exc:
            raise RuntimeError(
                "Vertex AI Search could not find Application Default Credentials. "
                "Run `gcloud auth application-default login` or configure a service account."
            ) from exc

        try:
            credentials.refresh(GoogleAuthRequest())
        except Exception as exc:  # pragma: no cover - depends on local auth state.
            raise RuntimeError(
                "Vertex AI Search could not obtain an access token. Re-authenticate "
                "with `gcloud auth application-default login` or fix the active "
                "service-account credentials."
            ) from exc

        return credentials

    def _serving_config_candidates(self) -> list[str]:
        configured = self.serving_config_id.strip() or "default_search"
        alternates = [configured]
        for candidate in ("default_search", "default_config"):
            if candidate not in alternates:
                alternates.append(candidate)
        return alternates

    def _params_candidates(self) -> list[dict[str, object]]:
        return [
            {"search_type": 1},
            {"searchType": 1},
        ]

    def _endpoint_url(self, serving_config_id: str) -> str:
        return (
            f"{self.BASE_URL}/projects/{self.project_id}"
            f"/locations/{self.location}"
            f"/collections/default_collection/engines/{self.app_id}"
            f"/servingConfigs/{serving_config_id}:search"
        )

    def _serving_config_path(self, serving_config_id: str) -> str:
        return (
            f"projects/{self.project_id}"
            f"/locations/{self.location}"
            f"/collections/default_collection/engines/{self.app_id}"
            f"/servingConfigs/{serving_config_id}"
        )

    def _normalize_result(
        self,
        item: dict[str, Any],
        query: str,
        index: int,
    ) -> dict[str, object]:
        document = item.get("document", {})
        if not isinstance(document, dict):
            document = {}

        result_data = document.get("derivedStructData", {})
        if not isinstance(result_data, dict):
            result_data = {}

        image_data = result_data.get("image", {})
        if not isinstance(image_data, dict):
            image_data = {}

        title = _first_text(
            result_data.get("title"),
            result_data.get("htmlTitle"),
            document.get("title"),
        )
        image_url = _first_text(result_data.get("link"), document.get("uri"))
        source_page_url = _first_text(
            image_data.get("contextLink"),
            result_data.get("contextLink"),
        )
        thumbnail_url = _first_text(image_data.get("thumbnailLink"))

        return {
            "query": query,
            "position": index,
            "title": title,
            "image_url": image_url,
            "source_page_url": source_page_url,
            "thumbnail_url": thumbnail_url,
            "display_link": _first_text(result_data.get("displayLink")),
            "mime": _first_text(result_data.get("mime")),
            "file_format": _first_text(result_data.get("fileFormat")),
            "width": image_data.get("width"),
            "height": image_data.get("height"),
            "thumbnail_width": image_data.get("thumbnailWidth"),
            "thumbnail_height": image_data.get("thumbnailHeight"),
            "byte_size": image_data.get("byteSize"),
        }


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


@lru_cache(maxsize=1)
def get_vertex_ai_image_search_service() -> VertexAiImageSearchService:
    return VertexAiImageSearchService()
