from types import SimpleNamespace

import pytest

from app.main import validate_startup_vision_model
from app.vision.client import VisionConfigurationError
from app.vision.model_check import validate_configured_model_available


class FakeModels:
    def __init__(self, model_ids: list[str]) -> None:
        self.model_ids = model_ids

    async def list(self) -> SimpleNamespace:
        return SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in self.model_ids])


class FakeOpenAIClient:
    def __init__(self, model_ids: list[str]) -> None:
        self.models = FakeModels(model_ids)


@pytest.mark.anyio
async def test_startup_model_check_skips_when_openai_key_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SKIP_MODEL_CHECK", raising=False)
    monkeypatch.setenv("VISION_MODEL", "missing-model")

    await validate_startup_vision_model()


@pytest.mark.anyio
async def test_configured_model_check_passes_when_model_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODEL", "gpt-test-vision")

    model = await validate_configured_model_available(
        client=FakeOpenAIClient(["gpt-other", "gpt-test-vision"])
    )

    assert model == "gpt-test-vision"


@pytest.mark.anyio
async def test_configured_model_check_raises_when_model_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODEL", "missing-model")

    with pytest.raises(VisionConfigurationError, match="missing-model"):
        await validate_configured_model_available(client=FakeOpenAIClient(["gpt-other"]))
