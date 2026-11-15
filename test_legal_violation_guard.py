from app.ai.legal_analyst import apply_deterministic_checks


def test_applicable_law_without_violation_does_not_confirm_risk():
    result = {
        "contract_terms": [
            {
                "category": "Срок оплаты",
                "description": "Оплата производится после приёмки товара.",
                "risk_level": "Высокий",
                "legal_basis": "Статья 34, часть 13",
                "legal_basis_status": "Статья и часть найдены",
                "legal_basis_text": "Текст проверенной правовой нормы.",
                "legal_applicability_status": "Применима",
                "legal_applicability_reason": "Норма регулирует условие оплаты.",
                "legal_applicability_evidence": "Оплата производится после приёмки товара.",
            }
        ]
    }

    checked = apply_deterministic_checks(
        result=result,
        document_text="44-ФЗ. Оплата производится после приёмки товара.",
        procurement_law="44-ФЗ",
    )

    item = checked["contract_terms"][0]

    assert item["risk_level"] == "Не определён"


if __name__ == "__main__":
    test_applicable_law_without_violation_does_not_confirm_risk()
    print("ТЕСТ ПРОЙДЕН")
