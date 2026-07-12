import json
import time
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from app.vision.client import VisionConfigurationError
from scripts import readiness_check


class FakeHttpResponse:
    def __init__(self, *, status: int, payload: dict) -> None:
        self.status = status
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_readiness_failure_includes_exception_type_and_message() -> None:
    result = readiness_check.failure(
        "check",
        time.perf_counter(),
        VisionConfigurationError("Configured VISION_MODEL 'bad-model' was not found."),
    )

    assert result["error"] == "VisionConfigurationError"
    assert result["message"] == "Configured VISION_MODEL 'bad-model' was not found."


def test_readiness_failure_includes_http_error_response_body() -> None:
    body = {
        "message": "Please provide an image and all required label fields.",
        "errors": {"image": "Image file is required."},
    }
    error = HTTPError(
        url="http://testserver/verify",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=BytesIO(json.dumps(body).encode("utf-8")),
    )

    result = readiness_check.failure("POST http://testserver/verify", time.perf_counter(), error)

    assert result["status"] == 400
    assert result["error"] == "HTTPError"
    assert result["response_body"] == body


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


def test_check_verify_runs_sequential_requests_and_reports_latency_stats(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "label.jpg"
    image_path.write_bytes(b"fake image bytes")
    latencies = [1000, 1400, 1200, 2000, 1600]
    responses = [
        FakeHttpResponse(
            status=200,
            payload={
                "verification": {"overall_verdict": "APPROVED"},
                "latency_ms": latency,
            },
        )
        for latency in latencies
    ]
    calls = 0

    def fake_urlopen(req, timeout):
        nonlocal calls
        response = responses[calls]
        calls += 1
        return response

    monkeypatch.setattr(readiness_check.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("READINESS_LABEL_IMAGE", str(image_path))
    for field in readiness_check.REQUIRED_FIELDS:
        monkeypatch.setenv(f"READINESS_{field.upper()}", f"sample {field}")

    result = readiness_check.check_verify("http://testserver/verify", runs=5)

    assert calls == 5
    assert result["ok"] is True
    assert result["runs"] == 5
    assert result["api_latency_ms_values"] == latencies
    assert result["api_latency_p50_ms"] == 1400
    assert result["api_latency_p95_ms"] == 2000
    assert result["overall_verdicts"] == ["APPROVED"] * 5


def test_percentile_nearest_rank() -> None:
    values = [1000, 1400, 1200, 2000, 1600]

    assert readiness_check.percentile_nearest_rank(values, 50) == 1400
    assert readiness_check.percentile_nearest_rank(values, 95) == 2000
    assert readiness_check.percentile_nearest_rank([], 95) is None
