import os

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
    """Отправляет запрос в Gemini и возвращает текстовый ответ."""

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

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            GEMINI_URL,
            headers=headers,
            json=payload,
        )

        response.raise_for_status()
        result = response.json()

    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(
            f"Gemini вернул неожиданный ответ: {result}"
        )
