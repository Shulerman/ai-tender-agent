from app.ai.technical_analyst import validate_analysis_evidence
from app.ai.technical_models import (
    TechnicalAnalysis,
    ProductAnalysis,
    DeliveryRequirement,
    DocumentRequirement,
    Risk,
)


def test_evidence_statuses_are_assigned_in_all_sections():
    document = (
        "Поставка товара в течение 10 дней. "
        "Товар должен иметь сертификат качества."
    )

    analysis = TechnicalAnalysis(
        products=[
            ProductAnalysis(
                name="Товар",
                quantity="1",
                unit="шт.",
                quotes=["Поставка товара в течение 10 дней."],
            )
        ],
        delivery_requirements=[
            DeliveryRequirement(
                delivery_time="10 дней",
                quotes=["Поставка товара в течение 5 дней."],
            )
        ],
        document_requirements=[
            DocumentRequirement(
                requirement_type="Сертификат",
                quotes=[
                    "Товар должен иметь сертификат качества.",
                    "Обязателен дополнительный паспорт.",
                ],
            )
        ],
        risks_and_uncertainties=[
            Risk(
                description="Неясные условия",
                quotes=[],
            )
        ],
        questions_to_customer=[],
    )

    validate_analysis_evidence(analysis, document)

    assert analysis.products[0].evidence_status == "Подтверждено"
    assert analysis.products[0].rejected_quotes == []

    assert analysis.delivery_requirements[0].evidence_status == "Не подтверждено"
    assert analysis.delivery_requirements[0].rejected_quotes == [
        "Поставка товара в течение 5 дней."
    ]

    assert analysis.document_requirements[0].evidence_status == "Частично подтверждено"
    assert analysis.document_requirements[0].quotes == [
        "Товар должен иметь сертификат качества."
    ]
    assert analysis.document_requirements[0].rejected_quotes == [
        "Обязателен дополнительный паспорт."
    ]

    assert analysis.risks_and_uncertainties[0].evidence_status == "Не подтверждено"
