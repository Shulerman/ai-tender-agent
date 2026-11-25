import pytest

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



@pytest.mark.asyncio
async def test_analyze_technical_requirements_runs_semantic_validation(
    monkeypatch,
):
    import json

    from app.ai import technical_analyst

    payload = {
        "products": [
            {
                "name": "Тестовый товар",
                "quantity": "10",
                "unit": "шт.",
                "attributes": [
                    {
                        "name": "Диаметр",
                        "value": "20",
                        "unit": "мм",
                        "operator": ">=",
                        "is_required": True,
                        "evidence": [
                            {
                                "claim": "Диаметр не менее 20 мм",
                                "quote": "Диаметр изделия — не менее 20 мм",
                            }
                        ],
                    }
                ],
                "quotes": [],
                "evidence": [],
            }
        ],
        "technical_requirements": [
            {
                "name": "Температура эксплуатации",
                "value": "-10 до +40",
                "unit": "°C",
                "operator": None,
                "is_required": True,
                "description": "",
                "quotes": [],
                "evidence": [
                    {
                        "claim": "Температура от -10 до +40 °C",
                        "quote": "Температура эксплуатации от -10 до +40 °C",
                    }
                ],
            }
        ],
        "delivery_requirements": [],
        "document_requirements": [],
        "risks_and_uncertainties": [],
        "questions_to_customer": [],
    }
    calls = []

    async def fake_generate_text(prompt, json_mode=False):
        return json.dumps(payload, ensure_ascii=False)

    async def fake_validate(analysis):
        calls.append(analysis)
        analysis.products[0].attributes[0].evidence[0].relevance_status = (
            "Подтверждает"
        )
        analysis.products[0].attributes[0].evidence[0].relevance_explanation = (
            "Число и оператор соответствуют цитате."
        )
        analysis.technical_requirements[0].evidence[0].relevance_status = (
            "Подтверждает"
        )
        analysis.technical_requirements[0].evidence[0].relevance_explanation = (
            "Значение соответствует цитате."
        )

    monkeypatch.setattr(technical_analyst, "generate_text", fake_generate_text)
    monkeypatch.setattr(
        technical_analyst,
        "validate_evidence_relevance",
        fake_validate,
    )

    result = await technical_analyst.analyze_technical_requirements(
        (
            "Техническое задание: Диаметр изделия — не менее 20 мм. "
            "Температура эксплуатации от -10 до +40 °C"
        )
    )

    assert len(calls) == 1
    evidence = result["products"][0]["attributes"][0]["evidence"][0]
    assert result["technical_requirements"][0]["name"] == (
        "Температура эксплуатации"
    )
    assert result["technical_requirements"][0]["evidence"][0][
        "relevance_status"
    ] == "Подтверждает"
    assert evidence["relevance_status"] == "Подтверждает"
    assert evidence["relevance_explanation"] == (
        "Число и оператор соответствуют цитате."
    )

@pytest.mark.asyncio
async def test_invalid_json_response_is_not_saved(monkeypatch):
    from app.ai import technical_analyst

    raw_response = '  {"broken":  \n'

    async def fake_generate_text(prompt, json_mode=False):
        return raw_response

    monkeypatch.setattr(technical_analyst, "generate_text", fake_generate_text)

    with pytest.raises(RuntimeError, match="некорректный JSON") as error:
        await technical_analyst.analyze_technical_requirements("Тестовый документ")

    message = str(error.value)
    assert "строка" in message
    assert "позиция" in message
    assert "длина ответа:" in message
    assert "gemini_json_error_" not in message
    assert raw_response not in message

@pytest.mark.asyncio
async def test_invalid_json_error_preserves_json_decode_cause(monkeypatch):
    import json

    from app.ai import technical_analyst

    raw_response = '{"broken":'

    async def fake_generate_text(prompt, json_mode=False):
        return raw_response

    monkeypatch.setattr(technical_analyst, "generate_text", fake_generate_text)

    with pytest.raises(RuntimeError, match="некорректный JSON") as error:
        await technical_analyst.analyze_technical_requirements("Тестовый документ")

    assert isinstance(error.value.__cause__, json.JSONDecodeError)
    assert raw_response not in str(error.value)

@pytest.mark.asyncio
async def test_questions_to_customer_prompt_requires_json_strings(monkeypatch):
    import json

    from app.ai import technical_analyst

    captured = {}

    payload = {
        "products": [],
        "technical_requirements": [],
        "delivery_requirements": [],
        "document_requirements": [],
        "risks_and_uncertainties": [],
        "questions_to_customer": ["Какое количество требуется?"],
    }

    async def fake_generate_text(prompt, json_mode=False):
        captured["prompt"] = prompt
        captured["json_mode"] = json_mode
        return json.dumps(payload, ensure_ascii=False)

    async def fake_validate(analysis):
        return None

    monkeypatch.setattr(technical_analyst, "generate_text", fake_generate_text)
    monkeypatch.setattr(
        technical_analyst,
        "validate_evidence_relevance",
        fake_validate,
    )

    result = await technical_analyst.analyze_technical_requirements(
        "Тестовый документ"
    )

    prompt = captured["prompt"]
    assert captured["json_mode"] is True
    assert "questions_to_customer должен быть массивом обычных строк" in prompt
    assert "Каждый вопрос записывай отдельной JSON-строкой" in prompt
    assert "Не используй имена переменных, присваивания" in prompt
    assert '"questions_to_customer": [' in prompt
    assert '"Конкретный вопрос заказчику"' in prompt
    assert result["questions_to_customer"] == ["Какое количество требуется?"]
