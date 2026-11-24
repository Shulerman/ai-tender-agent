import asyncio

import pytest

from app.ai import gemini


def test_gemini_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GEMINI_ENABLED", raising=False)

    assert gemini.is_gemini_enabled() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_gemini_accepts_enabled_values(monkeypatch, value):
    monkeypatch.setenv("GEMINI_ENABLED", value)

    assert gemini.is_gemini_enabled() is True


def test_generate_text_refuses_request_when_gemini_is_disabled(monkeypatch):
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="Gemini отключён"):
        asyncio.run(gemini.generate_text("Тестовый запрос"))
