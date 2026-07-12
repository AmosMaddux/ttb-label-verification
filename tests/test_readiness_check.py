import time

from app.vision.client import VisionConfigurationError
from scripts import readiness_check


def test_readiness_failure_includes_exception_type_and_message() -> None:
    result = readiness_check.failure(
        "check",
        time.perf_counter(),
        VisionConfigurationError("Configured VISION_MODEL 'bad-model' was not found."),
    )

    assert result["error"] == "VisionConfigurationError"
    assert result["message"] == "Configured VISION_MODEL 'bad-model' was not found."


def test_check_model_failure_includes_missing_model_message(monkeypatch) -> None:
    async def fake_validate_configured_model_available() -> str:
        raise VisionConfigurationError("Configured VISION_MODEL 'bad-model' was not found.")

    monkeypatch.setattr(
        readiness_check,
        "validate_configured_model_available",
        fake_validate_configured_model_available,
    )

    result = readiness_check.check_model()

    assert result["ok"] is False
    assert result["error"] == "VisionConfigurationError"
    assert result["message"] == "Configured VISION_MODEL 'bad-model' was not found."
