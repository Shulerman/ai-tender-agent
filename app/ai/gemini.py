
import os
import asyncio
import httpx


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

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не найден")

    if not prompt.strip():
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

    last_error = None

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
                last_error = error

                if error.response.status_code not in (429, 500, 502, 503, 504):
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
                last_error = error

                if attempt == 2:
                    raise RuntimeError(
                        "Не удалось связаться с Gemini "
                        "после трёх попыток."
                    ) from error

            await asyncio.sleep(2 ** attempt)

    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]

    except (KeyError, IndexError, TypeError):
        raise RuntimeError(
            f"Gemini вернул неожиданный ответ: {result}"
        )
