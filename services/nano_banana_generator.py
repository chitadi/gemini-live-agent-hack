from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from google import genai
from google.genai import types

from config import get_settings


DEFAULT_REDESIGN_IMAGE_MODEL = "gemini-2.5-flash-image"
REMOTE_IMAGE_TIMEOUT_SEC = 15


@dataclass(frozen=True)
class ReferenceImage:
    label: str
    data: bytes
    mime_type: str


class NanoBananaGeneratorService:
    def __init__(self) -> None:
        settings = get_settings()
        self.project_id = settings.google_cloud_project
        self.location = settings.google_cloud_location
        self.model = os.getenv("REDESIGN_IMAGE_MODEL", DEFAULT_REDESIGN_IMAGE_MODEL)
        self._client = genai.Client(
            vertexai=True,
            project=self.project_id,
            location=self.location,
        )

    def download_reference_image(
        self,
        *,
        url: str,
        fallback_label: str,
    ) -> ReferenceImage:
        cleaned_url = url.strip()
        if not cleaned_url:
            raise ValueError("Reference image URL must not be empty.")

        request = Request(
            cleaned_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                )
            },
        )

        try:
            with urlopen(request, timeout=REMOTE_IMAGE_TIMEOUT_SEC) as response:
                data = response.read()
                mime_type = response.headers.get_content_type()
        except HTTPError as exc:
            raise RuntimeError(
                f"Reference image download failed with HTTP {exc.code}: {cleaned_url}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Reference image download failed: {exc.reason}"
            ) from exc

        if not data:
            raise RuntimeError(f"Reference image download returned no bytes: {cleaned_url}")

        if not mime_type.startswith("image/"):
            raise RuntimeError(
                f"Reference image URL did not return an image content type: {cleaned_url}"
            )

        return ReferenceImage(
            label=fallback_label.strip() or "Reference image",
            data=data,
            mime_type=mime_type,
        )

    def generate_redesign(
        self,
        *,
        design_brief: str,
        inspiration_queries: list[str],
        room_images: list[ReferenceImage],
        inspiration_images: list[ReferenceImage],
        context_summary: str,
    ) -> dict[str, object]:
        if not room_images:
            raise ValueError("At least one room snapshot is required.")

        if not inspiration_images:
            raise ValueError("At least one inspiration image is required.")

        response = self._client.models.generate_content(
            model=self.model,
            contents=self._build_contents(
                design_brief=design_brief,
                inspiration_queries=inspiration_queries,
                room_images=room_images,
                inspiration_images=inspiration_images,
                context_summary=context_summary,
            ),
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        generated_image = self._extract_generated_image(response)
        generated_text = self._extract_generated_text(response)
        return {
            "image_bytes": generated_image.data,
            "mime_type": generated_image.mime_type or "image/png",
            "text": generated_text,
            "model": self.model,
        }

    def _build_contents(
        self,
        *,
        design_brief: str,
        inspiration_queries: list[str],
        room_images: list[ReferenceImage],
        inspiration_images: list[ReferenceImage],
        context_summary: str,
    ) -> list[str | types.Part]:
        cleaned_brief = design_brief.strip()
        query_summary = ", ".join(query.strip() for query in inspiration_queries if query.strip())
        cleaned_context = context_summary.strip()
        if not cleaned_brief:
            cleaned_brief = "Create a polished redesign that matches the saved inspiration."
        if not query_summary:
            query_summary = "Use the saved inspiration references only where they fit the room."
        if not cleaned_context:
            cleaned_context = "Use the saved room and vibe context to decide what to add or change."

        contents: list[str | types.Part] = [
            (
                "Create a single redesigned room image using the provided room snapshots as the base. "
                "The room snapshots are the primary source; match the geometry, layout, and camera angle. "
                "You may change materials, colors, and lighting, but do not alter the core room structure "
                "unless the brief explicitly asks for structural changes. "
                "Use inspiration images only as targeted edit references for specific elements, not as the "
                "source of the scene. Do not treat inspiration images as equally important to the room snapshots. "
                "If an inspiration image clearly shows a specific item that also exists in the room "
                "(e.g., bed, sofa, curtains, wall art), use it to redesign that item. Otherwise, ignore it. "
                "Do not make a collage. Produce a cohesive, photorealistic final redesign.\n\n"
                f"User brief: {cleaned_brief}\n"
                f"Context for edits: {cleaned_context}\n"
                f"Inspiration themes: {query_summary}"
            ),
            "Room snapshots to preserve:",
        ]

        for room_image in room_images:
            contents.append(room_image.label)
            contents.append(
                types.Part.from_bytes(
                    data=room_image.data,
                    mime_type=room_image.mime_type,
                )
            )

        contents.append("Inspiration references to borrow from selectively:")
        for inspiration_image in inspiration_images:
            contents.append(inspiration_image.label)
            contents.append(
                types.Part.from_bytes(
                    data=inspiration_image.data,
                    mime_type=inspiration_image.mime_type,
                )
            )

        return contents

    def _extract_generated_image(
        self, response: types.GenerateContentResponse
    ) -> types.Blob:
        for part in _iter_response_parts(response):
            if not part.inline_data:
                continue
            if (part.inline_data.mime_type or "").startswith("image/"):
                return part.inline_data

        raise RuntimeError("Nano Banana did not return an image in the response.")

    def _extract_generated_text(
        self, response: types.GenerateContentResponse
    ) -> str:
        text_parts: list[str] = []
        for part in _iter_response_parts(response):
            if part.text:
                text_parts.append(part.text.strip())
        return "\n".join(text for text in text_parts if text)


def _iter_response_parts(
    response: types.GenerateContentResponse,
) -> list[types.Part]:
    parts: list[types.Part] = []
    for candidate in response.candidates or []:
        if candidate.content and candidate.content.parts:
            parts.extend(candidate.content.parts)
    return parts


@lru_cache(maxsize=1)
def get_nano_banana_generator_service() -> NanoBananaGeneratorService:
    return NanoBananaGeneratorService()
