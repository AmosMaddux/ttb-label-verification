"""Startup/readiness validation for configured vision models."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any, Mapping

from app.vision.client import VisionConfigurationError
from app.vision.service import DEFAULT_VISION_MODEL


logger = logging.getLogger(__name__)


def should_skip_model_check() -> bool:
    """Return whether live model validation should be skipped.

    Inputs:
        Environment variables: `OPENAI_API_KEY`, `SKIP_MODEL_CHECK`, and
        `APP_ENV`.

    Outputs:
        `True` when the app should avoid a live OpenAI models-list call.
    """
    return (
        not os.environ.get("OPENAI_API_KEY")
        or _truthy(os.environ.get("SKIP_MODEL_CHECK"))
        or os.environ.get("APP_ENV", "").lower() == "test"
    )


async def validate_configured_model_if_enabled() -> str | None:
    """Validate the configured model unless startup checks are disabled.

    Inputs:
        Environment configuration.

    Outputs:
        The validated model name, or `None` when the check is skipped.
    """
    if should_skip_model_check():
        logger.info("Skipping live VISION_MODEL startup validation.")
        return None
    return await validate_configured_model_available()


async def validate_configured_model_available(client: Any | None = None) -> str:
    """Confirm the configured `VISION_MODEL` exists in OpenAI's model list.

    Inputs:
        Optional OpenAI-compatible client with `models.list()` for tests. When
        omitted, a real `AsyncOpenAI` client is constructed from environment
        variables.

    Outputs:
        The configured model name when it is present.

    Raises:
        `VisionConfigurationError` when API configuration is missing or the
        configured model is absent from the live model list.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if client is None:
        if not api_key:
            raise VisionConfigurationError("OPENAI_API_KEY is required to verify VISION_MODEL.")

        from openai import AsyncOpenAI

        timeout = float(os.environ.get("VISION_TIMEOUT_S", "4.5"))
        client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    model = os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL)
    response = await client.models.list()
    model_ids = set(_extract_model_ids(response))

    if model not in model_ids:
        raise VisionConfigurationError(
            f"Configured VISION_MODEL '{model}' was not found in OpenAI's available model list."
        )
    return model


def _extract_model_ids(response: Any) -> Iterable[str]:
    """Extract model IDs from OpenAI SDK list responses or test fakes."""
    models = getattr(response, "data", response)
    for item in models or []:
        if isinstance(item, Mapping):
            model_id = item.get("id")
        else:
            model_id = getattr(item, "id", None)
        if isinstance(model_id, str):
            yield model_id


def _truthy(value: str | None) -> bool:
    """Parse common truthy environment values."""
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}
