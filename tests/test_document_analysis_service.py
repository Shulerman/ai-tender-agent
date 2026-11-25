from types import SimpleNamespace

from app.documents.analysis_service import (
    _build_requirement_records,
    _find_source_chunk,
)


def test_find_source_chunk_returns_unique_exact_source():
    chunk = SimpleNamespace(
        id=10,
        text="Поставка товара в течение 10 рабочих дней.",
    )

    result = _find_source_chunk(
        "в течение 10 рабочих дней",
        [chunk],
    )

    assert result is chunk


def test_find_source_chunk_returns_none_when_quote_is_ambiguous():
    first = SimpleNamespace(
        id=10,
        text="Поставка товара в течение 10 рабочих дней.",
    )
    second = SimpleNamespace(
        id=11,
        text="Срок поставки: в течение 10 рабочих дней.",
    )

    result = _find_source_chunk(
        "в течение 10 рабочих дней",
        [first, second],
    )

    assert result is None


def test_find_source_chunk_returns_none_when_quote_is_missing():
    chunk = SimpleNamespace(
        id=10,
        text="Поставка товара в течение 10 рабочих дней.",
    )

    result = _find_source_chunk(
        "Поставка в течение 5 дней",
        [chunk],
    )

    assert result is None


def test_build_requirement_records_preserves_unverified_source_status():
    chunk = SimpleNamespace(
        id=10,
        text="Поставка товара в течение 10 рабочих дней.",
    )

    records = _build_requirement_records(
        analysis_result={
            "products": [
                {
                    "name": "Тестовый товар",
                    "quantity": "10",
                    "unit": "шт.",
                    "technical_characteristics": "Не указано",
                    "packaging_requirements": "Не указано",
                    "quality_and_standards": "Не указано",
                    "quotes": ["Поставка товара в течение 10 рабочих дней."],
                    "evidence": [],
                }
            ],
            "delivery_requirements": [],
            "document_requirements": [],
            "risks_and_uncertainties": [],
        },
        chunks=[chunk],
        analysis_id=20,
        document_id=30,
    )

    assert len(records) == 1
    assert records[0].requirement_type == "product"
    assert records[0].requirement_text == "Тестовый товар"
    assert records[0].source_chunk_id == 10
    assert records[0].evidence_quote == (
        "Поставка товара в течение 10 рабочих дней."
    )
    assert records[0].confidence is None
    assert records[0].extraction_status == "Источник найден"


def test_build_requirement_records_does_not_assign_ambiguous_source():
    first = SimpleNamespace(
        id=10,
        text="Поставка товара в течение 10 рабочих дней.",
    )
    second = SimpleNamespace(
        id=11,
        text="Срок поставки: в течение 10 рабочих дней.",
    )

    records = _build_requirement_records(
        analysis_result={
            "products": [
                {
                    "name": "Тестовый товар",
                    "quantity": "10",
                    "unit": "шт.",
                    "quotes": ["в течение 10 рабочих дней"],
                    "evidence": [],
                }
            ],
            "delivery_requirements": [],
            "document_requirements": [],
            "risks_and_uncertainties": [],
        },
        chunks=[first, second],
        analysis_id=20,
        document_id=30,
    )

    assert len(records) == 1
    assert records[0].source_chunk_id is None
    assert records[0].evidence_quote is None
    assert records[0].extraction_status == "Требует проверки"



def test_build_requirement_records_preserves_general_technical_requirement():
    chunk = SimpleNamespace(
        id=41,
        text="Общие требования: эксплуатация при температуре от -10 до +40 °C.",
    )
    records = _build_requirement_records(
        analysis_result={
            "products": [],
            "technical_requirements": [
                {
                    "name": "Температура эксплуатации",
                    "value": "-10 до +40",
                    "unit": "°C",
                    "operator": None,
                    "is_required": True,
                    "description": "",
                    "quotes": [
                        "эксплуатация при температуре от -10 до +40 °C"
                    ],
                    "evidence": [
                        {
                            "claim": "Допустимая температура от -10 до +40 °C",
                            "quote": (
                                "эксплуатация при температуре от -10 до +40 °C"
                            ),
                            "relevance_status": "Недостаточно данных",
                        }
                    ],
                }
            ],
            "delivery_requirements": [],
            "document_requirements": [],
            "risks_and_uncertainties": [],
        },
        chunks=[chunk],
        analysis_id=20,
        document_id=30,
    )

    assert len(records) == 1
    record = records[0]
    assert record.requirement_type == "technical"
    assert record.requirement_text == (
        "Температура эксплуатации: -10 до +40 °C"
    )
    assert record.source_chunk_id == 41
    assert record.extraction_status == "Источник найден"
    assert record.attributes["is_required"] is True
    assert record.attributes["semantic_evidence_status"] == "Не подтверждено"
    assert (
        record.attributes["evidence"][0]["relevance_status"]
        == "Недостаточно данных"
    )


def test_semantic_evidence_status_requires_all_evidence_to_confirm():
    from app.documents.analysis_service import _semantic_evidence_status

    assert _semantic_evidence_status({"evidence": []}) == "Не проверено"
    assert _semantic_evidence_status({
        "evidence": [
            {"relevance_status": "Подтверждает"},
            {"relevance_status": "Ожидает проверки"},
        ]
    }) == "Не подтверждено"
    assert _semantic_evidence_status({
        "evidence": [
            {"relevance_status": "Подтверждает"},
            {"relevance_status": "Подтверждает"},
        ]
    }) == "Подтверждено"
    assert _semantic_evidence_status({
        "evidence": [{"relevance_status": "Противоречит"}]
    }) == "Противоречит"
