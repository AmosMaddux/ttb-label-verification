"""Configuration helpers for vision-related environment variables."""

from __future__ import annotations

import os
from collections.abc import Callable


class VisionConfigurationError(RuntimeError):
    """Raised when real vision extraction cannot be configured."""


def env_float(name: str, default: float) -> float:
    """Read a float environment variable with a clear configuration error."""
    return _parse_env(name, default, float)


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a clear configuration error."""
    return _parse_env(name, default, int)


def _parse_env(name: str, default: int | float, parser: Callable[[str], int | float]) -> int | float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return parser(raw_value)
    except ValueError as exc:
        raise VisionConfigurationError(
            f"{name} must be a valid {parser.__name__}; got {raw_value!r}."
        ) from exc
