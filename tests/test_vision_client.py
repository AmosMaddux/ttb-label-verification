import sys
from types import SimpleNamespace

import pytest

from app.vision.client import (
    ALLOWED_REASONING_EFFORTS,
    ALLOWED_SERVICE_TIERS,
    OpenAIVisionClient,
    VisionConfigurationError,
)


class FakeResponses:
    calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="{}", output=[], service_tier="priority")


class FakeAsyncOpenAI:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        self.responses = FakeResponses()


def install_fake_openai(monkeypatch) -> type[FakeAsyncOpenAI]:
    FakeAsyncOpenAI.calls = []
    FakeResponses.calls = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    return FakeAsyncOpenAI


def test_openai_vision_client_uses_default_timeout(monkeypatch) -> None:
    fake_openai = install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("VISION_TIMEOUT_S", raising=False)

    OpenAIVisionClient()

    assert fake_openai.calls == [{"api_key": "test-key", "timeout": 4.0}]


def test_openai_vision_client_honors_timeout_env(monkeypatch) -> None:
    fake_openai = install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_TIMEOUT_S", "2.0")

    OpenAIVisionClient()

    assert fake_openai.calls == [{"api_key": "test-key", "timeout": 2.0}]


def test_openai_vision_client_rejects_invalid_timeout_env(monkeypatch) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_TIMEOUT_S", "fast")

    with pytest.raises(VisionConfigurationError, match="VISION_TIMEOUT_S"):
        OpenAIVisionClient()


@pytest.mark.anyio
async def test_openai_request_omits_latency_options_when_unset(monkeypatch) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("VISION_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("OPENAI_SERVICE_TIER", raising=False)

    client = OpenAIVisionClient()
    await client.extract_structured_label(
        image_bytes=b"image",
        prompt="extract",
        schema={"type": "object"},
        model="gpt-test",
        detail="high",
    )

    request = FakeResponses.calls[0]
    assert "reasoning" not in request
    assert "service_tier" not in request


@pytest.mark.anyio
async def test_openai_request_omits_blank_latency_options(monkeypatch) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_REASONING_EFFORT", "")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "")

    client = OpenAIVisionClient()
    await client.extract_structured_label(
        image_bytes=b"image",
        prompt="extract",
        schema={"type": "object"},
        model="gpt-test",
        detail="high",
    )

    request = FakeResponses.calls[0]
    assert "reasoning" not in request
    assert "service_tier" not in request


@pytest.mark.anyio
@pytest.mark.parametrize("reasoning_effort", sorted(ALLOWED_REASONING_EFFORTS))
async def test_openai_request_passes_configured_reasoning_effort(
    monkeypatch,
    reasoning_effort: str,
) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_REASONING_EFFORT", reasoning_effort)
    monkeypatch.delenv("OPENAI_SERVICE_TIER", raising=False)

    client = OpenAIVisionClient()
    await client.extract_structured_label(
        image_bytes=b"image",
        prompt="extract",
        schema={"type": "object"},
        model="gpt-test",
        detail="high",
    )

    assert FakeResponses.calls[0]["reasoning"] == {"effort": reasoning_effort}
    assert "service_tier" not in FakeResponses.calls[0]


@pytest.mark.anyio
@pytest.mark.parametrize("service_tier", sorted(ALLOWED_SERVICE_TIERS))
async def test_openai_request_passes_configured_service_tier(
    monkeypatch,
    service_tier: str,
) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("VISION_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("OPENAI_SERVICE_TIER", service_tier)

    client = OpenAIVisionClient()
    await client.extract_structured_label(
        image_bytes=b"image",
        prompt="extract",
        schema={"type": "object"},
        model="gpt-test",
        detail="high",
    )

    assert "reasoning" not in FakeResponses.calls[0]
    assert FakeResponses.calls[0]["service_tier"] == service_tier


@pytest.mark.anyio
async def test_openai_request_passes_reasoning_and_service_tier_together(monkeypatch) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_REASONING_EFFORT", "none")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "priority")

    client = OpenAIVisionClient()
    result = await client.extract_structured_label(
        image_bytes=b"image",
        prompt="extract",
        schema={"type": "object"},
        model="gpt-test",
        detail="high",
    )

    assert FakeResponses.calls[0]["reasoning"] == {"effort": "none"}
    assert FakeResponses.calls[0]["service_tier"] == "priority"
    assert result.response_service_tier == "priority"


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("VISION_REASONING_EFFORT", "fastest"),
        ("OPENAI_SERVICE_TIER", "premium"),
    ],
)
def test_openai_vision_client_rejects_invalid_latency_option_env(
    monkeypatch,
    env_var: str,
    value: str,
) -> None:
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(env_var, value)

    with pytest.raises(VisionConfigurationError, match=env_var):
        OpenAIVisionClient()
