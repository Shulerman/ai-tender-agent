import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import analyze_legal_requirements


async def main():
    document_text = (
        "44-ФЗ. "
        "Предмет закупки: поставка бумажной продукции. "
        "Пункт 8.1. "
        "Обеспечение исполнения контракта предоставляется поставщиком."
    )

    document_quote = (
        "Обеспечение исполнения контракта предоставляется поставщиком."
    )

    main_response = {
        "procurement_law": "44-ФЗ",
        "procurement_type": "Поставка бумажной продукции",
        "contract_terms": [
            {
                "category": "Обеспечение исполнения контракта",
                "description": (
                    "Поставщик предоставляет обеспечение исполнения контракта."
                ),
                "risk_level": "Высокий",
                "commercial_risk_level": "Недостаточно информации",
                "commercial_risk_reason": (
                    "Неизвестен размер обеспечения."
                ),
                "document_clause": "Пункт 8.1",
                "document_quote": document_quote,
                "legal_basis": "Статья 96",
                "legal_basis_status": "Требует проверки",
                "recommendation": "Проверить условия обеспечения.",
            }
        ],
        "risks": [],
        "commercial_risks": [
            {
                "category": "Логистика",
                "description": "Неизвестен объём поставки.",
                "commercial_risk_level": "Недостаточно информации",
                "commercial_risk_reason": "Нет данных об объёме партии.",
                "document_clause": "Не указано",
                "document_quote": "Не указано",
                "recommendation": "Уточнить объём поставки.",
            }
        ],
        "contradictions": [],
        "missing_information": ["Размер обеспечения исполнения контракта."],
        "questions_to_customer": ["Каков размер обеспечения?"],
        "overall_conclusion": "Требуется дополнительная проверка.",
    }

    applicability_response = {
        "results": [
            {
                "id": "contract_terms_0",
                "applicability_status": "Применима",
                "applicability_reason": (
                    "Статья регулирует обеспечение исполнения контракта."
                ),
                "applicability_evidence": document_quote,
                "violation_status": "Недостаточно информации",
                "violation_reason": (
                    "Недостаточно данных для установления нарушения."
                ),
                "document_evidence": "",
                "legal_evidence": "",
            }
        ]
    }

    with patch(
        "app.ai.legal_analyst.generate_text",
        new_callable=AsyncMock,
        side_effect=[
            json.dumps(main_response, ensure_ascii=False),
            json.dumps(applicability_response, ensure_ascii=False),
        ],
    ) as mocked_gemini:
        result = await analyze_legal_requirements(document_text)

    assert mocked_gemini.await_count == 2, (
        f"Ожидалось 2 обращения к Gemini, получено: "
        f"{mocked_gemini.await_count}"
    )

    assert result["procurement_law"] == "44-ФЗ"
    assert result["procurement_type"] == "Поставка бумажной продукции"

    assert len(result["contract_terms"]) == 1
    item = result["contract_terms"][0]

    assert item["legal_basis_status"] in {
        "Статья найдена",
        "Статья и часть найдены",
        "Структура нормы найдена",
    }, (
        "Правовая ссылка не подтверждена локальной базой: "
        f"{item['legal_basis_status']}"
    )

    assert item["legal_basis_text"] not in {
        "",
        "Не найдено",
        "Не указано",
        "Не проверено",
    }

    assert item["legal_applicability_status"] == "Применима"
    assert item["legal_violation_status"] == "Недостаточно информации"

    assert item["risk_level"] == "Не определён", (
        "Юридический риск не должен подтверждаться без установленного нарушения."
    )

    assert item["document_quote"] == document_quote

    assert len(result["commercial_risks"]) == 1
    commercial = result["commercial_risks"][0]

    assert commercial["commercial_risk_level"] == "Недостаточно информации"
    assert commercial["commercial_risk_reason"] == (
        "Нет данных об объёме партии."
    )

    assert result["missing_information"] == [
        "Размер обеспечения исполнения контракта."
    ]
    assert result["questions_to_customer"] == [
        "Каков размер обеспечения?"
    ]

    print("ПОЛНЫЙ ИНТЕГРАЦИОННЫЙ ТЕСТ ПРОЙДЕН")
    print("1. Закон и предмет закупки определены.")
    print("2. Правовая ссылка проверена по локальной базе.")
    print("3. Текст правовой нормы получен из базы.")
    print("4. Применимость нормы проверена отдельно.")
    print("5. Отсутствие доказанного нарушения не превратилось в юридический риск.")
    print("6. Коммерческий риск сохранён без изменений.")
    print("7. Отсутствующая информация и вопросы сохранены.")
    print("8. Выполнено ровно два обращения к Gemini mock — реальных API-запросов нет.")


asyncio.run(main())
