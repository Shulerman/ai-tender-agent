import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import check_legal_applicability


async def main():
    document_quote = (
        "Заказчик устанавливает срок оплаты 90 календарных дней."
    )
    legal_text = (
        "Срок оплаты не должен превышать 30 календарных дней."
    )

    result = {
        "contract_terms": [
            {
                "category": "Срок оплаты",
                "description": "Срок оплаты составляет 90 дней.",
                "document_clause": "Пункт 5.2",
                "document_quote": document_quote,
                "legal_basis": "Статья 34",
                "legal_basis_status": "Статья найдена",
                "legal_basis_text": legal_text,
            }
        ],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [],
    }

    gemini_response = {
        "results": [
            {
                "id": "contract_terms_0",
                "applicability_status": "Применима",
                "applicability_reason": "Норма регулирует срок оплаты.",
                "applicability_evidence": legal_text,
                "violation_status": "Нарушение установлено",
                "violation_reason": (
                    "Указанный в документе срок превышает "
                    "ограничение из переданной нормы."
                ),
                "document_evidence": document_quote,
                "legal_evidence": legal_text,
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
    assert item["legal_violation_status"] == "Нарушение установлено"
    assert document_quote in item["legal_violation_evidence"]
    assert legal_text in item["legal_violation_evidence"]

    print("ТЕСТ ПОДТВЕРЖДЁННОГО НАРУШЕНИЯ ПРОЙДЕН")
    print("1. Применимость нормы подтверждена.")
    print("2. Нарушение установлено.")
    print("3. Цитата документа совпадает с исходным текстом.")
    print("4. Цитата правовой нормы совпадает с переданным текстом.")
    print("5. Реальных API-запросов не было.")


asyncio.run(main())
