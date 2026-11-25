import asyncio

import httpx
import pytest

from app.ai import gemini


class FakeResponse:
    def __init__(self, payload=None, status_code=200, invalid_json=False):
        self.payload = payload
        self.status_code = status_code
        self.invalid_json = invalid_json
        self.headers = {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            response = httpx.Response(
                self.status_code,
                headers=self.headers,
                content=self.text,
                request=httpx.Request("POST", gemini.GEMINI_URL),
            )
            response.raise_for_status()

    def json(self):
        if self.invalid_json:
            raise ValueError("invalid JSON")
        return self.payload


class FakeAsyncClient:
    def __init__(self, responses, calls, timeout):
        self.responses = responses
        self.calls = calls
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers, json):
        self.calls.append({
            "url": url,
            "headers": headers,
            "json": json,
        })
        return self.responses.pop(0)


def install_fake_client(monkeypatch, responses):
    calls = []

    def factory(timeout):
        return FakeAsyncClient(responses, calls, timeout)

    monkeypatch.setattr(gemini.httpx, "AsyncClient", factory)
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    return calls


def successful_response(parts=None):
    if parts is None:
        parts = [{"text": '{"ok": true}'}]

    return FakeResponse({
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": parts},
        }]
    })


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


def test_generate_text_returns_text_and_uses_json_mode(monkeypatch):
    calls = install_fake_client(
        monkeypatch,
        [successful_response()],
    )

    result = asyncio.run(
        gemini.generate_text("Тестовый запрос", json_mode=True)
    )

    assert result == '{"ok": true}'
    assert len(calls) == 1
    assert calls[0]["json"]["generationConfig"] == {
        "responseMimeType": "application/json"
    }
    assert calls[0]["headers"]["x-goog-api-key"] == "test-key"


def test_generate_text_combines_all_text_parts(monkeypatch):
    install_fake_client(
        monkeypatch,
        [successful_response([
            {"text": '{"value":'},
            {"text": ' "complete"}'},
        ])],
    )

    result = asyncio.run(gemini.generate_text("Тест"))

    assert result == '{"value": "complete"}'


@pytest.mark.parametrize(
    "finish_reason",
    ["MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", None],
)
def test_generate_text_rejects_incomplete_generation(
    monkeypatch,
    finish_reason,
):
    calls = install_fake_client(
        monkeypatch,
        [FakeResponse({
            "candidates": [{
                "finishReason": finish_reason,
                "content": {"parts": [{"text": "Секретный фрагмент"}]},
            }]
        })],
    )

    with pytest.raises(RuntimeError, match="без подтверждения полного ответа") as error:
        asyncio.run(gemini.generate_text("Тест"))

    assert "Секретный фрагмент" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [None]},
        {"candidates": [{"finishReason": "STOP"}]},
        {"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": []},
        }]},
    ],
)
def test_generate_text_rejects_unexpected_response_structure(
    monkeypatch,
    payload,
):
    install_fake_client(
        monkeypatch,
        [FakeResponse(payload)],
    )

    with pytest.raises(RuntimeError, match="Gemini"):
        asyncio.run(gemini.generate_text("Тест"))


def test_generate_text_rejects_invalid_api_json(monkeypatch):
    install_fake_client(
        monkeypatch,
        [FakeResponse(invalid_json=True)],
    )

    with pytest.raises(RuntimeError, match="некорректный JSON-ответ API"):
        asyncio.run(gemini.generate_text("Тест"))


def test_generate_text_retries_temporary_http_error(monkeypatch):
    calls = install_fake_client(
        monkeypatch,
        [
            FakeResponse(status_code=503),
            successful_response(),
        ],
    )

    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(gemini.asyncio, "sleep", fake_sleep)

    result = asyncio.run(gemini.generate_text("Тест"))

    assert result == '{"ok": true}'
    assert len(calls) == 2
    assert delays == [1]


def test_generate_text_does_not_retry_non_temporary_http_error(monkeypatch):
    calls = install_fake_client(
        monkeypatch,
        [FakeResponse(status_code=400)],
    )

    with pytest.raises(RuntimeError, match="HTTP 400"):
        asyncio.run(gemini.generate_text("Тест"))

    assert len(calls) == 1

def test_generate_text_fails_after_three_temporary_http_errors(monkeypatch):
    calls = install_fake_client(
        monkeypatch,
        [
            FakeResponse(status_code=503),
            FakeResponse(status_code=503),
            FakeResponse(status_code=503),
        ],
    )

    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(gemini.asyncio, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="после трёх попыток"):
        asyncio.run(gemini.generate_text("Тест"))

    assert len(calls) == 3
    assert delays == [1, 2]


def test_generate_text_reports_http_retry_details(monkeypatch):
    response = FakeResponse(status_code=503)
    response.headers = {
        "Retry-After": "7",
        "x-request-id": "test-request-123",
    }
    response.text = '{"error":{"message":"backend temporarily unavailable"}}'

    calls = install_fake_client(
        monkeypatch,
        [response, FakeResponse(status_code=503), response],
    )

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr("app.ai.gemini.asyncio.sleep", fake_sleep)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(gemini.generate_text("test prompt"))

    message = str(exc_info.value)
    assert "HTTP 503" in message
    assert "Retry-After=7" in message
    assert "Request-ID=test-request-123" in message
    assert "backend temporarily unavailable" in message
    assert len(calls) == 3
