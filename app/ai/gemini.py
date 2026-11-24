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

            try:
                response = await client.post(
                    GEMINI_URL,
                    headers=headers,
                    json=payload,
                )

                response.raise_for_status()
                result = response.json()
                break

            except httpx.HTTPStatusError as error:

                if error.response.status_code not in (
                    429, 500, 502, 503, 504
                ):
                    raise RuntimeError(
                        f"Ошибка Gemini API: HTTP "
                        f"{error.response.status_code}"
                    ) from error

                if attempt == 2:
                    raise RuntimeError(
                        "Gemini временно недоступен после "
                        "трёх попыток. Попробуйте позже."
                    ) from error

            except (httpx.TimeoutException, httpx.NetworkError) as error:

                if attempt == 2:
                    raise RuntimeError(
                        "Не удалось связаться с Gemini "
                        "после трёх попыток."
                    ) from error

            await asyncio.sleep(2 ** attempt)

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini вернул пустой текст")

        return text

    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"Gemini вернул неожиданный ответ: {result}"
        ) from error
