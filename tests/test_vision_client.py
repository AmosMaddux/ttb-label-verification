import sys
from types import SimpleNamespace

from app.vision.client import OpenAIVisionClient


class FakeAsyncOpenAI:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def install_fake_openai(monkeypatch) -> type[FakeAsyncOpenAI]:
    FakeAsyncOpenAI.calls = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    return FakeAsyncOpenAI


def test_openai_vision_client_uses_default_timeout(monkeypatch) -> None:
    fake_openai = install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("VISION_TIMEOUT_S", raising=False)

    OpenAIVisionClient()

    assert fake_openai.calls == [{"api_key": "test-key", "timeout": 4.5}]


def test_openai_vision_client_honors_timeout_env(monkeypatch) -> None:
    fake_openai = install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VISION_TIMEOUT_S", "2.0")

    OpenAIVisionClient()

    assert fake_openai.calls == [{"api_key": "test-key", "timeout": 2.0}]
