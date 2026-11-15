import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ai.technical_analyst import analyze_technical_requirements


async def main():
    document_text = """
    Закупка проводится по 44-ФЗ.
    Предмет закупки: поставка бумаги.
    Бумага офисная А4, количество 100 пачек.
    Поставка в течение 10 рабочих дней.
    Адрес доставки: Москва.
    """

    mock_response = {
        "products": [
            {
                "name": "Бумага офисная А4",
                "quantity": "100",
                "unit": "пачек",
                "technical_characteristics": "Формат А4",
                "packaging_requirements": "Не указано",
                "quality_and_standards": "Не указано",
                "quotes": ["Бумага офисная А4, количество 100 пачек."]
            }
        ],
        "delivery_requirements": [
            {
                "delivery_time": "10 рабочих дней",
                "delivery_address": "Москва",
                "quotes": ["Поставка в течение 10 рабочих дней."]
            }
        ],
        "document_requirements": [],
        "risks_and_uncertainties": [],
        "questions_to_customer": []
    }

    with patch(
        "app.ai.technical_analyst.generate_text",
        new_callable=AsyncMock,
        return_value=json.dumps(mock_response, ensure_ascii=False),
    ) as mocked_gemini:
        result = await analyze_technical_requirements(document_text)

    assert mocked_gemini.await_count == 1
    assert len(result["products"]) == 1
    assert result["products"][0]["name"] == "Бумага офисная А4"
    assert result["products"][0]["quantity"] == "100"
    assert result["delivery_requirements"][0]["delivery_time"] == "10 рабочих дней"

    print("ТЕСТ ТЕХНИЧЕСКОГО АНАЛИЗАТОРА ПРОЙДЕН")
    print("1. Ответ Gemini успешно подменён.")
    print("2. Результат проверен через Pydantic.")
    print("3. Товар и количество извлечены.")
    print("4. Срок и адрес поставки сохранены.")
    print("5. Реальных API-запросов не было.")


if __name__ == "__main__":
    asyncio.run(main())
