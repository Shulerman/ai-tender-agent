from unittest.mock import patch

from app.ai.legal_analyst import (
    LEGAL_VERSION_IDS,
    apply_deterministic_checks,
    validate_legal_basis,
    extract_legal_basis_text,
)


def main():
    legal_basis = "Статья 999999"

    with patch(
        "app.ai.legal_analyst.get_legal_provision",
        return_value=None,
    ):
        status = validate_legal_basis(
            legal_basis=legal_basis,
            procurement_law="44-ФЗ",
            db=None,
            article_cache={},
        )

        legal_text = extract_legal_basis_text(
            legal_basis=legal_basis,
            procurement_law="44-ФЗ",
            db=None,
            article_cache={},
        )

    assert status == "Статья не найдена в локальной базе"
    assert legal_text == "Не найдено"

    result = {
        "contract_terms": [
            {
                "category": "Проверка отсутствующей статьи",
                "description": "Тестовое условие документа.",
                "risk_level": "Высокий",
                "legal_basis": legal_basis,
                "legal_basis_status": status,
                "legal_basis_text": legal_text,
                "legal_applicability_status": "Применима",
                "legal_violation_status": "Нарушение установлено",
                "legal_violation_reason": "Тестовое утверждение Gemini.",
                "legal_violation_evidence": (
                    "Документ: Тестовое условие документа. "
                    "| Правовая норма: Тестовое требование."
                ),
            }
        ],
        "risks": [],
        "contradictions": [],
        "commercial_risks": [],
    }

    checked = apply_deterministic_checks(
        result=result,
        document_text="44-ФЗ. Тестовое условие документа.",
        procurement_law="44-ФЗ",
    )

    item = checked["contract_terms"][0]

    assert item["risk_level"] == "Не определён", (
        "ОШИБКА: риск подтверждён без найденной правовой нормы."
    )

    print("ТЕСТ ОТСУТСТВУЮЩЕЙ ПРАВОВОЙ ССЫЛКИ ПРОЙДЕН")
    print("1. Несуществующая статья не найдена в локальной базе.")
    print("2. Текст отсутствующей нормы не был получен.")
    print("3. Даже при заявлении Gemini о нарушении риск не подтверждён.")
    print("4. Итоговый юридический риск: Не определён.")


main()
