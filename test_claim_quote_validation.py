from app.ai.technical_analyst import validate_analysis_evidence
from app.ai.technical_models import TechnicalAnalysis, ProductAnalysis


def create_analysis(evidence):
    return TechnicalAnalysis(
        products=[
            ProductAnalysis(
                name="Товар",
                quantity="10",
                unit="шт.",
                evidence=evidence,
            )
        ],
        delivery_requirements=[],
        document_requirements=[],
        risks_and_uncertainties=[],
        questions_to_customer=[],
    )


def test_existing_quote_waits_for_semantic_verification():
    document = "Поставка товара осуществляется в течение 10 дней."

    analysis = create_analysis([
        {
            "claim": "Срок поставки составляет 10 дней.",
            "quote": "Поставка товара осуществляется в течение 10 дней.",
        }
    ])

    validate_analysis_evidence(analysis, document)

    evidence = analysis.products[0].evidence[0]

    assert evidence.relevance_status == "Ожидает проверки"
    assert "ещё не проверено" in evidence.relevance_explanation


def test_missing_quote_is_rejected():
    document = "Поставка товара осуществляется в течение 10 дней."

    analysis = create_analysis([
        {
            "claim": "Срок поставки составляет 5 дней.",
            "quote": "Поставка товара осуществляется в течение 5 дней.",
        }
    ])

    validate_analysis_evidence(analysis, document)

    evidence = analysis.products[0].evidence[0]

    assert evidence.relevance_status == "Цитата не найдена"
    assert "отсутствует" in evidence.relevance_explanation
