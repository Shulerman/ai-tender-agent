import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import check_legal_applicability


async def main():
    result = {
        "contract_terms": [
            {
                "category": "Обеспечение исполнения контракта",
                "description": "Поставщик предоставляет обеспечение исполнения контракта.",
                "document_clause": "Пункт 8.1",
                "document_quote": (
                    "Обеспечение исполнения контракта "
                    "предоставляется поставщиком."
                ),
                "legal_basis": "Статья 96 44-ФЗ",
                "legal_basis_status": "Статья найдена",
                "legal_basis_text": (
                    "Заказчик устанавливает требование обеспечения "
                    "исполнения контракта в соответствии с настоящей статьёй."
                ),
            }
        ],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [
            {
                "category": "Логистика",
                "description": "Неизвестен объём поставки",
                "commercial_risk_level": "Недостаточно информации",
                "commercial_risk_reason": "Нет данных об объёме партии.",
            }
        ],
    }

    gemini_response = {
        "results": [
            {
                "id": "contract_terms_0",
                "applicability_status": "Применима",
                "applicability_reason": (
                    "Предмет переданного условия относится к регулированию "
                    "обеспечения исполнения контракта."
                ),
                "applicability_evidence": (
                    "Обеспечение исполнения контракта "
                    "предоставляется поставщиком."
                ),
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
        return_value=json.dumps(gemini_response, ensure_ascii=False),
    ) as mocked:
        checked = await check_legal_applicability(result)

    assert mocked.await_count == 1

    item = checked["contract_terms"][0]

    assert item["legal_applicability_status"] == "Применима"
    assert (
        item["legal_applicability_reason"]
        == gemini_response["results"][0]["applicability_reason"]
    )
    assert (
        item["legal_applicability_evidence"]
        == gemini_response["results"][0]["applicability_evidence"]
    )

    assert (
        item["legal_violation_status"]
        == "Недостаточно информации"
    )

    commercial = checked["commercial_risks"][0]

    assert commercial["commercial_risk_level"] == "Недостаточно информации"
    assert commercial["commercial_risk_reason"] == "Нет данных об объёме партии."

    print("ТЕСТ УСПЕШНОГО ОТВЕТА ПРОЙДЕН")
    print("1. Статус «Применима» корректно сохранён.")
    print("2. Объяснение и доказательство сохранены.")
    print("3. Отсутствие доказанного нарушения не подменяется подтверждением.")
    print("4. Коммерческие риски не изменены.")


asyncio.run(main())
