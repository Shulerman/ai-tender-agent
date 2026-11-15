import asyncio
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import check_legal_applicability


async def main():
    result = {
        "contract_terms": [
            {
                "category": "Срок поставки",
                "description": "Поставка в течение 10 дней",
                "legal_basis": "Статья 34 44-ФЗ",
                "legal_basis_status": "Статья найдена",
                "legal_basis_text": "Текст нормы для тестирования",
            },
            {
                "category": "Оплата",
                "description": "Оплата после поставки",
                "legal_basis": "Не найдено",
                "legal_basis_status": "Не найдено",
                "legal_basis_text": "Не найдено",
            },
        ],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [
            {
                "category": "Логистика",
                "description": "Неизвестен объём поставки",
                "commercial_risk_level": "Недостаточно информации",
            }
        ],
    }

    with patch(
        "app.ai.legal_analyst.generate_text",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Тестовая недоступность Gemini"),
    ) as mocked:
        checked = await check_legal_applicability(result)

    assert mocked.await_count == 1

    first = checked["contract_terms"][0]
    second = checked["contract_terms"][1]
    commercial = checked["commercial_risks"][0]

    assert first["legal_applicability_status"] == "Требует проверки"
    assert "не выполнена" in first["legal_applicability_reason"].lower()

    assert second["legal_applicability_status"] == "Требует проверки"

    assert commercial["commercial_risk_level"] == "Недостаточно информации"

    print("ТЕСТ ПРОЙДЕН")
    print("1. Ошибка Gemini не прерывает анализ.")
    print("2. Непроверенная применимость сохраняет осторожный статус.")
    print("3. Коммерческие риски не изменяются.")


asyncio.run(main())
