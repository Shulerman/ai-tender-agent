import json

import pytest

from app.ai import evidence_relevance_validator as validator
from pathlib import Path

from app.ai.technical_models import (
    DeliveryRequirement,
    Evidence,
    ProductAnalysis,
    ProductAttribute,
    TechnicalAnalysis,
    TechnicalRequirement,
)


def make_analysis():
    return TechnicalAnalysis(
        products=[
            ProductAnalysis(
                name="Тестовый товар",
                quantity="10",
                unit="шт.",
                evidence=[
                    Evidence(
                        claim="Требуется тестовый товар",
                        quote="Требуется тестовый товар",
                        relevance_status="Ожидает проверки",
                    )
                ],
                attributes=[
                    ProductAttribute(
                        name="Диаметр",
                        value="20",
                        unit="мм",
                        evidence=[
                            Evidence(
                                claim="Диаметр не менее 20 мм",
                                quote="Диаметр изделия — не менее 20 мм",
                                relevance_status="Ожидает проверки",
                            ),
                            Evidence(
                                claim="Старая запись",
                                quote="Старая цитата",
                                relevance_status="Цитата не найдена",
                            ),
                        ],
                    )
                ],
            )
        ],
        technical_requirements=[
            TechnicalRequirement(
                name="Температура эксплуатации",
                value="-10 до +40",
                unit="°C",
                evidence=[
                    Evidence(
                        claim="Температура от -10 до +40 °C",
                        quote="Температура эксплуатации от -10 до +40 °C",
                        relevance_status="Ожидает проверки",
                    )
                ],
            )
        ],
        delivery_requirements=[
            DeliveryRequirement(
                delivery_time="10 дней",
                evidence=[
                    Evidence(
                        claim="Поставка за 10 дней",
                        quote="Поставка в течение 10 дней",
                        relevance_status="Ожидает проверки",
                    )
                ],
            )
        ],
        document_requirements=[],
        risks_and_uncertainties=[],
        questions_to_customer=[],
    )


def test_collect_evidence_includes_product_attribute_and_delivery():
    analysis = make_analysis()

    collected = validator.collect_evidence(analysis)

    assert [item["id"] for item in collected] == [
        "product-0-0",
        "product-attribute-0-0-0",
        "technical-0-0",
        "delivery-0-0",
    ]
    assert len({item["id"] for item in collected}) == len(collected)
    assert all(item["evidence_object"].relevance_status == "Ожидает проверки"
               for item in collected)


@pytest.mark.asyncio
async def test_validate_evidence_relevance_applies_gemini_results(monkeypatch):
    analysis = make_analysis()
    collected = validator.collect_evidence(analysis)
    statuses = (
        "Подтверждает",
        "Недостаточно данных",
        "Противоречит",
        "Подтверждает",
    )
    payload = {
        "results": [
            {
                "id": item["id"],
                "status": status,
                "explanation": f"Проверено: {status}",
            }
            for item, status in zip(collected, statuses)
        ]
    }
    calls = []

    async def fake_generate_text(prompt, json_mode=False):
        calls.append((prompt, json_mode))
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(validator, "generate_text", fake_generate_text)

    await validator.validate_evidence_relevance(analysis)

    assert len(calls) == 1
    assert calls[0][1] is True
    assert "Диаметр не менее 20 мм" in calls[0][0]
    assert [
        item["evidence_object"].relevance_status for item in collected
    ] == list(statuses)
    assert all(
        item["evidence_object"].relevance_explanation.startswith("Проверено:")
        for item in collected
    )


@pytest.mark.asyncio
async def test_validate_evidence_relevance_handles_malformed_ids_and_results(
    monkeypatch,
):
    analysis = make_analysis()
    collected = validator.collect_evidence(analysis)
    first_id = collected[0]["id"]

    async def fake_generate_text(prompt, json_mode=False):
        return json.dumps({
            "results": [
                {"id": [], "status": "Подтверждает", "explanation": "x"},
                {"id": first_id, "status": [], "explanation": "x"},
                {
                    "id": first_id,
                    "status": "Подтверждает",
                    "explanation": "Дубликат не должен заменить первый результат",
                },
                {
                    "id": "unknown-id",
                    "status": "Подтверждает",
                    "explanation": "Неизвестный ID",
                },
            ]
        }, ensure_ascii=False)

    monkeypatch.setattr(validator, "generate_text", fake_generate_text)

    await validator.validate_evidence_relevance(analysis)

    assert collected[0]["evidence_object"].relevance_status == (
        "Проверка не выполнена"
    )
    assert all(
        item["evidence_object"].relevance_status == "Проверка не выполнена"
        for item in collected
    )


@pytest.mark.asyncio
async def test_validate_evidence_relevance_fails_closed_on_gemini_exception(
    monkeypatch,
):
    analysis = make_analysis()

    async def failing_generate_text(prompt, json_mode=False):
        raise OSError("transport failure")

    monkeypatch.setattr(validator, "generate_text", failing_generate_text)

    await validator.validate_evidence_relevance(analysis)

    for item in validator.collect_evidence(analysis):
        assert item["evidence_object"].relevance_status == (
            "Проверка не выполнена"
        )


@pytest.mark.asyncio
async def test_validate_evidence_relevance_skips_empty_queue(monkeypatch):
    analysis = make_analysis()
    for item in validator.collect_evidence(analysis):
        item["evidence_object"].relevance_status = "Цитата не найдена"

    async def unexpected_generate_text(prompt, json_mode=False):
        raise AssertionError("Gemini не должен вызываться без доказательств")

    monkeypatch.setattr(validator, "generate_text", unexpected_generate_text)

    await validator.validate_evidence_relevance(analysis)


@pytest.mark.asyncio
async def test_validator_saves_safe_diagnostic_on_gemini_exception(
    monkeypatch, tmp_path, caplog
):
    analysis = make_analysis()
    secret = "test-gemini-secret-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setattr(validator.tempfile, "tempdir", str(tmp_path))
    caplog.set_level("WARNING", logger=validator.__name__)

    async def failing_generate_text(prompt, json_mode=False):
        try:
            raise TimeoutError("socket timed out")
        except TimeoutError as cause:
            raise OSError(
                "request failed: "
                f"https://example.invalid/generate?key={secret} "
                "Bearer test-bearer-secret"
            ) from cause

    monkeypatch.setattr(validator, "generate_text", failing_generate_text)

    await validator.validate_evidence_relevance(analysis)

    records = [
        record for record in caplog.records
        if record.name == validator.__name__
    ]
    assert len(records) == 1
    assert "OSError" in records[0].getMessage()
    assert "diagnostic=" in records[0].getMessage()

    diagnostic_path = Path(
        records[0].getMessage().split("diagnostic=", 1)[1].strip()
    )
    assert diagnostic_path.is_file()
    diagnostic_text = diagnostic_path.read_text(encoding="utf-8")

    assert "OSError" in diagnostic_text
    assert "request failed" in diagnostic_text
    assert "TimeoutError" in diagnostic_text
    assert "socket timed out" in diagnostic_text
    assert "Traceback" in diagnostic_text
    assert secret not in diagnostic_text
    assert "test-bearer-secret" not in diagnostic_text
    assert diagnostic_text.count("[REDACTED]") >= 2
    assert "Требуется тестовый товар" not in diagnostic_text

    for item in validator.collect_evidence(analysis):
        assert item["evidence_object"].relevance_status == (
            "Проверка не выполнена"
        )
