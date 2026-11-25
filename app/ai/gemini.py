import os
import asyncio
import httpx

from dotenv import load_dotenv


load_dotenv()


def is_gemini_enabled() -> bool:
    """Проверяет глобальное разрешение на передачу данных в Gemini."""

    value = os.getenv("GEMINI_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)


async def generate_text(prompt: str, json_mode: bool = False) -> str:
    """Отправляет запрос в Gemini с повторными попытками."""

    if not is_gemini_enabled():
        raise RuntimeError(
            "Gemini отключён. Установите GEMINI_ENABLED=true "
            "в настройках окружения."
        )

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не найден")

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Текст запроса не должен быть пустым")

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    if json_mode:
        payload["generationConfig"] = {
            "responseMimeType": "application/json"
        }

    async with httpx.AsyncClient(timeout=90) as client:

        for attempt in range(3):

            retry_delay = 2 ** attempt

            try:
                response = await client.post(
                    GEMINI_URL,
                    headers=headers,
                    json=payload,
                )

                response.raise_for_status()

                try:
                    result = response.json()
                except (ValueError, TypeError) as error:
                    raise RuntimeError(
                        "Gemini вернул некорректный JSON-ответ API"
                    ) from error

                break

            except httpx.HTTPStatusError as error:

                if error.response.status_code not in (
                    429, 500, 502, 503, 504
                ):
                    raise RuntimeError(
                        f"Ошибка Gemini API: HTTP "
                        f"{error.response.status_code}"
                    ) from error

                retry_after = error.response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        parsed_retry_after = int(retry_after.strip())
                        if parsed_retry_after >= 0:
                            retry_delay = min(parsed_retry_after, 30)
                    except (AttributeError, TypeError, ValueError):
                        pass

                if attempt == 2:
                    request_id = (
                        error.response.headers.get("x-request-id")
                        or error.response.headers.get("request-id")
                    )
                    try:
                        error_body = error.response.text[:500]
                    except Exception:
                        error_body = ""

                    details = [
                        f"HTTP {error.response.status_code}"
                    ]
                    if retry_after:
                        details.append(f"Retry-After={retry_after}")
                    if request_id:
                        details.append(f"Request-ID={request_id}")
                    if error_body:
                        details.append(f"Ответ сервера: {error_body}")

                    raise RuntimeError(
                        "Gemini временно недоступен после трёх попыток. "
                        + "; ".join(details)
                    ) from error

            except (httpx.TimeoutException, httpx.NetworkError) as error:

                if attempt == 2:
                    raise RuntimeError(
                        "Не удалось связаться с Gemini "
                        "после трёх попыток."
                    ) from error

            await asyncio.sleep(retry_delay)

    if not isinstance(result, dict):
        raise RuntimeError(
            "Gemini вернул ответ неожиданной структуры"
        )

    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError(
            "Gemini не вернул кандидатов с текстом ответа"
        )

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise RuntimeError(
            "Gemini вернул ответ неожиданной структуры"
        )

    finish_reason = candidate.get("finishReason")
    if finish_reason != "STOP":
        reason = finish_reason if isinstance(finish_reason, str) else "не указан"
        raise RuntimeError(
            "Gemini завершил генерацию без подтверждения полного ответа "
            f"(finishReason={reason})"
        )

    content = candidate.get("content")
    if not isinstance(content, dict):
        raise RuntimeError(
            "Gemini не вернул содержимое ответа"
        )

    parts = content.get("parts")
    if not isinstance(parts, list):
        raise RuntimeError(
            "Gemini вернул ответ без списка текстовых частей"
        )

    text_parts = [
        part["text"]
        for part in parts
        if (
            isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        )
    ]

    text = "".join(text_parts)

    if not text.strip():
        raise RuntimeError(
            "Gemini вернул пустой текст"
        )

    return text
