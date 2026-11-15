import asyncio
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import check_legal_applicability


def make_result():
    return {
        "contract_terms": [
            {
                "category": "Срок оплаты",
                "description": "Оплата после приёмки.",
                "document_clause": "Пункт 5.1",
                "document_quote": "Оплата производится после приёмки.",
                "legal_basis": "Статья 34",
                "legal_basis_status": "Статья найдена",
                "legal_basis_text": "Текст проверенной правовой нормы.",
            }
        ],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [
            {
                "category": "Логистика",
                "description": "Неизвестен объём поставки.",
                "commercial_risk_level": "Недостаточно информации",
                "commercial_risk_reason": "Нет данных об объёме партии.",
            }
        ],
    }


async def main():
    # Сценарий 1. Gemini завершился ошибкой.
    result = make_result()

    with patch(
        "app.ai.legal_analyst.generate_text",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Тестовая ошибка Gemini"),
    ) as mocked:
        checked = await check_legal_applicability(result)

    assert mocked.await_count == 1

    item = checked["contract_terms"][0]

    assert item["legal_applicability_status"] == "Требует проверки"
    assert item["legal_violation_status"] == "Требует проверки"
    assert "не выполнена" in item["legal_applicability_reason"].lower()
    assert "не выполнена" in item["legal_violation_reason"].lower()

    commercial = checked["commercial_risks"][0]
    assert commercial["commercial_risk_level"] == "Недостаточно информации"
    assert commercial["commercial_risk_reason"] == (
        "Нет данных об объёме партии."
    )

    print("Сценарий 1 пройден: ошибка Gemini не прерывает анализ.")
    print("Статусы применимости и нарушения остались осторожными.")
    print("Коммерческий риск сохранён.")

    # Сценарий 2. Правовая ссылка не подтверждена.
    result = make_result()
    result["contract_terms"][0]["legal_basis_status"] = (
        "Статья не найдена в локальной базе"
    )
    result["contract_terms"][0]["legal_basis_text"] = "Не найдено"

    with patch(
        "app.ai.legal_analyst.generate_text",
        new_callable=AsyncMock,
    ) as mocked:
        checked = await check_legal_applicability(result)

    assert mocked.await_count == 0

    item = checked["contract_terms"][0]

    assert item["legal_applicability_status"] == "Требует проверки"
    assert item["legal_violation_status"] == "Требует проверки"
    assert "не подтверждены" in item["legal_applicability_reason"].lower()
    assert "не подтверждены" in item["legal_violation_reason"].lower()

    print("Сценарий 2 пройден: неподтверждённая ссылка не отправлена Gemini.")
    print("Обе юридические проверки оставлены на дополнительную проверку.")

    print("\nТЕСТ ОБРАБОТКИ СБОЕВ GEMINI ПРОЙДЕН")
    print("Реальных API-запросов не было.")


asyncio.run(main())
