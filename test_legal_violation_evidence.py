import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ai.legal_analyst import check_legal_applicability


DOCUMENT_QUOTE = (
    "Срок оплаты составляет 90 календарных дней после приёмки товара."
)

LEGAL_TEXT = (
    "Оплата по контракту осуществляется не позднее 7 рабочих дней "
    "с даты подписания документа о приёмке."
)

DOCUMENT_EVIDENCE = "Срок оплаты составляет 90 календарных дней"
LEGAL_EVIDENCE = "не позднее 7 рабочих дней"


def make_result():
    return {
        "contract_terms": [{
            "category": "Срок оплаты",
            "description": "Срок оплаты составляет 90 календарных дней.",
            "document_clause": "Пункт 5.2",
            "document_quote": DOCUMENT_QUOTE,
            "legal_basis": "Статья 34 44-ФЗ",
            "legal_basis_status": "Статья найдена",
            "legal_basis_text": LEGAL_TEXT,
        }],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [],
    }


async def run_case(document_evidence, legal_evidence):
    result = make_result()

    response = {
        "results": [{
            "id": "contract_terms_0",
            "applicability_status": "Применима",
            "applicability_reason": "Норма регулирует срок оплаты.",
            "applicability_evidence": DOCUMENT_QUOTE,
            "violation_status": "Нарушение установлено",
            "violation_reason": "Указанный срок противоречит требованию нормы.",
            "document_evidence": document_evidence,
            "legal_evidence": legal_evidence,
        }]
    }

    with patch(
        "app.ai.legal_analyst.generate_text",
        new_callable=AsyncMock,
        return_value=json.dumps(response, ensure_ascii=False),
    ):
        return await check_legal_applicability(result)


async def main():
    # Сценарий 1. Оба доказательства дословные.
    valid = await run_case(
        DOCUMENT_EVIDENCE,
        LEGAL_EVIDENCE,
    )

    valid_item = valid["contract_terms"][0]

    assert valid_item["legal_violation_status"] == "Нарушение установлено"
    assert DOCUMENT_EVIDENCE in valid_item["legal_violation_evidence"]
    assert LEGAL_EVIDENCE in valid_item["legal_violation_evidence"]

    # Сценарий 2. Доказательство из документа выдумано.
    invalid_document = await run_case(
        "Вымышленная цитата из документа.",
        LEGAL_EVIDENCE,
    )

    assert (
        invalid_document["contract_terms"][0]["legal_violation_status"]
        == "Требует проверки"
    )

    # Сценарий 3. Доказательство из закона выдумано.
    invalid_law = await run_case(
        DOCUMENT_EVIDENCE,
        "Вымышленная цитата из закона.",
    )

    assert (
        invalid_law["contract_terms"][0]["legal_violation_status"]
        == "Требует проверки"
    )

    # Сценарий 4. Оба доказательства выдуманы.
    invalid_both = await run_case(
        "Несуществующая цитата документа.",
        "Несуществующая цитата закона.",
    )

    assert (
        invalid_both["contract_terms"][0]["legal_violation_status"]
        == "Требует проверки"
    )

    print("ТЕСТ ДОКАЗАТЕЛЬСТВ НАРУШЕНИЯ ПРОЙДЕН")
    print("1. Две точные цитаты приняты.")
    print("2. Вымышленная цитата документа отклонена.")
    print("3. Вымышленная цитата закона отклонена.")
    print("4. Две вымышленные цитаты отклонены.")


asyncio.run(main())
