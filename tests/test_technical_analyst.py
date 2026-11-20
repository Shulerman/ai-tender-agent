from app.ai.technical_analyst import validate_analysis_evidence
from app.ai.technical_models import (
    Evidence,
    ProductAnalysis,
    ProductAttribute,
    TechnicalAnalysis,
)


def make_analysis(attribute_quote):
    return TechnicalAnalysis(
        products=[
            ProductAnalysis(
                name="Тестовый товар",
                quantity="10",
                unit="шт.",
                attributes=[
                    ProductAttribute(
                        name="Диаметр",
                        value="20",
                        unit="мм",
                        evidence=[
                            Evidence(
                                claim="Диаметр составляет 20 мм",
                                quote=attribute_quote,
                            )
                        ],
                    )
                ],
            )
        ],
        delivery_requirements=[],
        document_requirements=[],
        risks_and_uncertainties=[],
        questions_to_customer=[],
    )


def test_attribute_evidence_is_marked_when_quote_exists():
    analysis = make_analysis("Диаметр изделия — 20 мм.")
    document = "Технические характеристики: Диаметр изделия — 20 мм."

    validate_analysis_evidence(analysis, document)

    evidence = analysis.products[0].attributes[0].evidence[0]
    assert evidence.relevance_status == "Ожидает проверки"
    assert "Цитата найдена" in evidence.relevance_explanation


def test_attribute_evidence_is_rejected_when_quote_is_missing():
    analysis = make_analysis("Диаметр изделия — 25 мм.")
    document = "Технические характеристики: Диаметр изделия — 20 мм."

    validate_analysis_evidence(analysis, document)

    evidence = analysis.products[0].attributes[0].evidence[0]
    assert evidence.relevance_status == "Цитата не найдена"
    assert "отсутствует" in evidence.relevance_explanation
