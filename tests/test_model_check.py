import sys
from types import SimpleNamespace

import pytest

import app.main as main_module
from app.api.verify import _get_cached_vision_service
from app.main import close_cached_vision_service, validate_startup_vision_model
from app.vision.client import VisionConfigurationError
from app.vision.model_check import validate_configured_model_available
from app.vision.service import VisionService


class FakeModels:
    def __init__(self, model_ids: list[str]) -> None:
        self.model_ids = model_ids

    async def list(self) -> SimpleNamespace:
        return SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in self.model_ids])


class FakeOpenAIClient:
    def __init__(self, model_ids: list[str]) -> None:
        self.models = FakeModels(model_ids)


class PaginatedModelPage:
    def __init__(self, pages: list[list[str]], index: int = 0) -> None:
        self.pages = pages
        self.index = index
        self.data = [SimpleNamespace(id=model_id) for model_id in pages[index]]

    def has_next_page(self) -> bool:
        return self.index < len(self.pages) - 1

    async def get_next_page(self) -> "PaginatedModelPage":
        return PaginatedModelPage(self.pages, self.index + 1)


class PaginatedModels:
    def __init__(self, pages: list[list[str]]) -> None:
        self.pages = pages

    async def list(self) -> PaginatedModelPage:
        return PaginatedModelPage(self.pages)


class PaginatedOpenAIClient:
    def __init__(self, pages: list[list[str]]) -> None:
        self.models = PaginatedModels(pages)


class ClosableVisionClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def extract_structured_label(self, **kwargs):
        raise AssertionError("This fake should not extract labels.")


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


@pytest.mark.anyio
async def test_configured_model_check_finds_model_on_later_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODEL", "gpt-second-page")

    model = await validate_configured_model_available(
        client=PaginatedOpenAIClient([["gpt-first-page"], ["gpt-second-page"]])
    )

    assert model == "gpt-second-page"


@pytest.mark.anyio
async def test_configured_model_check_raises_when_model_missing_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VISION_MODEL", "missing-model")

    with pytest.raises(VisionConfigurationError, match="missing-model"):
        await validate_configured_model_available(
            client=PaginatedOpenAIClient([["gpt-first-page"], ["gpt-second-page"]])
        )


@pytest.mark.anyio
async def test_model_check_closes_temporary_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAsyncOpenAI:
        instance: "FakeAsyncOpenAI | None" = None

        def __init__(self, **kwargs: object) -> None:
            self.models = FakeModels(["gpt-test-vision"])
            self.closed = False
            FakeAsyncOpenAI.instance = self

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_MODEL", "gpt-test-vision")

    assert await validate_configured_model_available() == "gpt-test-vision"
    assert FakeAsyncOpenAI.instance is not None
    assert FakeAsyncOpenAI.instance.closed is True


@pytest.mark.anyio
async def test_lifespan_invokes_startup_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_validate_startup_vision_model() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(main_module, "validate_startup_vision_model", fake_validate_startup_vision_model)

    async with main_module.lifespan(main_module.app):
        assert calls == 1


@pytest.mark.anyio
async def test_lifespan_closes_and_clears_cached_vision_service(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ClosableVisionClient()
    service = VisionService(client=client)

    async def fake_validate_startup_vision_model() -> None:
        return None

    def fake_from_env() -> VisionService:
        return service

    _get_cached_vision_service.cache_clear()
    monkeypatch.setattr(main_module, "validate_startup_vision_model", fake_validate_startup_vision_model)
    monkeypatch.setattr(VisionService, "from_env", fake_from_env)

    async with main_module.lifespan(main_module.app):
        assert _get_cached_vision_service() is service
        assert client.closed is False

    assert client.closed is True
    assert _get_cached_vision_service.cache_info().currsize == 0


@pytest.mark.anyio
async def test_close_cached_vision_service_does_not_construct_when_cache_empty() -> None:
    _get_cached_vision_service.cache_clear()

    await close_cached_vision_service()

    assert _get_cached_vision_service.cache_info().currsize == 0
