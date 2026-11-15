import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import check_legal_applicability


async def run_case(evidence):
    result = {
        "contract_terms": [{
            "category": "Обеспечение",
            "description": "Поставщик предоставляет обеспечение контракта.",
            "document_clause": "Пункт 8.1",
            "document_quote": "Поставщик предоставляет обеспечение контракта.",
            "legal_basis": "Статья 96 44-ФЗ",
            "legal_basis_status": "Статья найдена",
            "legal_basis_text": "Текст нормы для теста.",
        }],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [],
    }

    response = {
        "results": [{
            "id": "contract_terms_0",
            "applicability_status": "Применима",
            "applicability_reason": "Проверка тестового условия.",
            "applicability_evidence": evidence,
            "violation_status": "Недостаточно информации",
            "violation_reason": "Для установления нарушения недостаточно данных.",
            "document_evidence": "",
            "legal_evidence": "",
        }]
    }

    with patch(
        "app.ai.legal_analyst.generate_text",
        new_callable=AsyncMock,
        return_value=json.dumps(response, ensure_ascii=False),
    ):
        return await check_legal_applicability(result)


async def main():
    empty = await run_case("")
    invented = await run_case("Несуществующая цитата из документа.")
    valid = await run_case(
        "Поставщик предоставляет обеспечение контракта."
    )

    assert (
        empty["contract_terms"][0]["legal_applicability_status"]
        == "Требует проверки"
    ), "Пустое доказательство не было отклонено."

    assert (
        invented["contract_terms"][0]["legal_applicability_status"]
        == "Требует проверки"
    ), "Вымышленное доказательство не было отклонено."

    assert (
        valid["contract_terms"][0]["legal_applicability_status"]
        == "Применима"
    ), "Дословное доказательство не было принято."

    print("ТЕСТ ЗАЩИТЫ ДОКАЗАТЕЛЬСТВ ПРОЙДЕН")
    print("1. Пустое доказательство отклонено.")
    print("2. Вымышленное доказательство отклонено.")
    print("3. Дословная цитата принята.")


asyncio.run(main())
