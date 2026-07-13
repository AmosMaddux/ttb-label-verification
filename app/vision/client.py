"""Vision provider client abstractions.

This module isolates the OpenAI Responses API call behind a small protocol so
the extraction service can be tested with fakes and swapped without changing the
API or comparison layers.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.vision.config import VisionConfigurationError, env_float


@dataclass(frozen=True)
class VisionClientResult:
    """Raw structured output returned by a vision client.

    Inputs:
        `structured_data` is a parsed mapping when the provider exposes one.
        `raw_json` is the provider's JSON text fallback.

    Outputs:
        A provider-neutral result consumed by `VisionService`.
    """

    structured_data: Mapping[str, Any] | None = None
    raw_json: str | None = None


class VisionClientProtocol(Protocol):
    """Protocol implemented by real and fake vision clients.

    Inputs:
        Implementations receive image bytes, the extraction prompt, JSON schema,
        model name, and image-detail setting.

    Outputs:
        A `VisionClientResult` containing either parsed structured data or raw
        JSON text.
    """

    async def extract_structured_label(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        schema: dict[str, Any],
        model: str,
        detail: str,
    ) -> VisionClientResult:
        ...


class OpenAIVisionClient:
    """OpenAI-backed implementation of `VisionClientProtocol`.

    Inputs:
        Optional API key. When omitted, the client reads `OPENAI_API_KEY` from
        environment variables.

    Outputs:
        An async client capable of returning structured label extraction data.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """Create the OpenAI async client.

        Inputs:
            Optional API key override.

        Outputs:
            An initialized `OpenAIVisionClient`, or `VisionConfigurationError`
            if no API key is available.
        """
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise VisionConfigurationError("OPENAI_API_KEY is required for real vision extraction.")

        from openai import AsyncOpenAI

        timeout = env_float("VISION_TIMEOUT_S", 4.0)
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    async def aclose(self) -> None:
        """Close the underlying async OpenAI client when supported."""
        for method_name in ("aclose", "close"):
            close = getattr(self._client, method_name, None)
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
                return

    async def extract_structured_label(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        schema: dict[str, Any],
        model: str,
        detail: str,
    ) -> VisionClientResult:
        """Request structured label extraction from OpenAI.

        Inputs:
            JPEG image bytes, extraction prompt, JSON schema, model name, and
            image-detail setting.

        Outputs:
            `VisionClientResult` with parsed output when available and raw JSON
            text as a fallback for the service parser.
        """
        image_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        response = await self._client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_url, "detail": detail},
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "extracted_label",
                    "schema": schema,
                    "strict": True,
                }
            },
        )

        structured = _find_parsed_output(response)
        raw_json = getattr(response, "output_text", None)
        return VisionClientResult(structured_data=structured, raw_json=raw_json)


def _find_parsed_output(response: object) -> Mapping[str, Any] | None:
    """Locate parsed structured data in a Responses API object.

    Inputs:
        The provider response object returned by `AsyncOpenAI.responses.create`.

    Outputs:
        A mapping containing parsed schema output when present, otherwise
        `None` so the service can fall back to raw JSON text.
    """
    direct = getattr(response, "output_parsed", None)
    if isinstance(direct, Mapping):
        return direct

    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            parsed = getattr(content, "parsed", None)
            if isinstance(parsed, Mapping):
                return parsed
    return None
