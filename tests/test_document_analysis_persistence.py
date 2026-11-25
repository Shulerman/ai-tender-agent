import asyncio
import uuid

import pytest

from app.database import SessionLocal
from app.documents import analysis_service
from app.documents.models import (
    DocumentChunkDB,
    TenderAnalysisDB,
    TenderDocumentDB,
    TenderRequirementDB,
)


@pytest.fixture
def document_with_chunks():
    db = SessionLocal()

    document = TenderDocumentDB(
        document_uuid=str(uuid.uuid4()),
        original_name="test_requirements.html",
        file_path="test_requirements.html",
        file_hash=None,
        detected_extension=".html",
        size_bytes=100,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    first_chunk = DocumentChunkDB(
        document_id=document.id,
        sequence_number=1,
        locator_type="paragraph",
        locator_value="1",
        text=(
            "Технические требования к товару. "
            "Общие требования: эксплуатация при температуре от -10 до +40 °C."
        ),
    )
    second_chunk = DocumentChunkDB(
        document_id=document.id,
        sequence_number=2,
        locator_type="paragraph",
        locator_value="2",
        text="Поставка товара в течение 10 рабочих дней.",
    )

    db.add_all([first_chunk, second_chunk])
    db.commit()
    db.refresh(first_chunk)
    db.refresh(second_chunk)

    try:
        yield db, document, first_chunk, second_chunk
    finally:
        document_id = document.id

        db.query(TenderRequirementDB).filter_by(
            document_id=document_id
        ).delete(synchronize_session=False)

        db.query(TenderAnalysisDB).filter_by(
            document_id=document_id
        ).delete(synchronize_session=False)

        db.query(DocumentChunkDB).filter_by(
            document_id=document_id
        ).delete(synchronize_session=False)

        db.query(TenderDocumentDB).filter_by(
            id=document_id
        ).delete(synchronize_session=False)

        db.commit()
        db.close()


def test_analyze_and_save_document_requirements(
    document_with_chunks,
    monkeypatch,
):
    db, document, first_chunk, second_chunk = document_with_chunks

    async def fake_analyzer(document_text):
        assert "Технические требования к товару." in document_text
        assert "Поставка товара в течение 10 рабочих дней." in document_text

        return {
            "products": [
                {
                    "name": "Тестовый товар",
                    "quantity": "10",
                    "unit": "шт.",
                    "technical_characteristics": "Не указано",
                    "packaging_requirements": "Не указано",
                    "quality_and_standards": "Не указано",
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
                                    "quote": "Диаметр изделия — не менее 20 мм.",
                                    "relevance_status": "Ожидает проверки",
                                    "relevance_explanation": "Цитата найдена.",
                                }
                            ],
                        }
                    ],
                    "quotes": [
                        "Поставка товара в течение 10 рабочих дней."
                    ],
                    "evidence": [],
                    "evidence_status": "Подтверждено",
                    "rejected_quotes": [],
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
                    "quotes": [
                        "эксплуатация при температуре от -10 до +40 °C"
                    ],
                    "evidence": [
                        {
                            "claim": "Эксплуатация от -10 до +40 °C",
                            "quote": (
                                "эксплуатация при температуре от -10 до +40 °C"
                            ),
                            "relevance_status": "Проверка не выполнена",
                            "relevance_explanation": "Тестовый статус.",
                        }
                    ],
                }
            ],
            "delivery_requirements": [],
            "document_requirements": [],
            "risks_and_uncertainties": [],
            "questions_to_customer": [],
        }

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )

    result = asyncio.run(
        analysis_service.analyze_and_save_document_requirements(
            db,
            document.id,
        )
    )

    assert result["status"] == "Завершён"
    assert result["requirements_count"] == 2
    assert result["requirements_with_source"] == 2

    analysis = db.get(TenderAnalysisDB, result["analysis_id"])

    assert analysis is not None
    assert analysis.document_id == document.id
    assert analysis.analysis_type == "technical_requirements"
    assert analysis.status == "Завершён"
    assert analysis.completed_at is not None
    assert analysis.result_json["products"][0]["name"] == "Тестовый товар"
    assert analysis.result_json["products"][0]["attributes"][0]["name"] == "Диаметр"

    requirements = db.query(TenderRequirementDB).filter_by(
        analysis_id=analysis.id
    ).all()
    assert len(requirements) == 2

    requirement = next(
        item for item in requirements
        if item.requirement_type == "product"
    )
    technical_requirement = next(
        item for item in requirements
        if item.requirement_type == "technical"
    )

    assert technical_requirement.requirement_text == (
        "Температура эксплуатации: -10 до +40 °C"
    )
    assert technical_requirement.source_chunk_id == first_chunk.id
    assert technical_requirement.extraction_status == "Источник найден"
    assert (
        technical_requirement.attributes["semantic_evidence_status"]
        == "Не подтверждено"
    )
    assert (
        technical_requirement.attributes["evidence"][0]["relevance_status"]
        == "Проверка не выполнена"
    )

    assert requirement.document_id == document.id
    assert requirement.requirement_type == "product"
    assert requirement.requirement_text == "Тестовый товар"
    assert requirement.source_chunk_id == second_chunk.id
    assert requirement.source_chunk_id != first_chunk.id
    assert requirement.evidence_quote == (
        "Поставка товара в течение 10 рабочих дней."
    )
    assert requirement.confidence is None
    assert requirement.extraction_status == "Источник найден"
    assert requirement.attributes["attributes"][0]["name"] == "Диаметр"
    assert requirement.attributes["attributes"][0]["operator"] == ">="
    assert requirement.attributes["attributes"][0]["evidence"][0]["quote"] == (
        "Диаметр изделия — не менее 20 мм."
    )



def test_persists_all_30_general_technical_requirements(
    document_with_chunks,
    monkeypatch,
):
    db, document, first_chunk, _ = document_with_chunks

    expected = []
    source_lines = []

    for number in range(1, 31):
        required = number % 3 == 0
        status = "обязательно" if required else "справочно"
        quote = (
            f"Параметр {number:02d} | "
            f"Значение {number:02d} | {status}"
        )
        source_lines.append(quote)
        expected.append({
            "name": f"Параметр {number:02d}",
            "value": f"Значение {number:02d}",
            "is_required": required,
            "quote": quote,
        })

    first_chunk.text = "\n".join(source_lines)
    db.commit()

    async def fake_analyzer(document_text):
        for item in expected:
            assert item["quote"] in document_text

        return {
            "products": [],
            "technical_requirements": [
                {
                    "name": item["name"],
                    "value": item["value"],
                    "unit": None,
                    "operator": None,
                    "is_required": item["is_required"],
                    "description": "",
                    "quotes": [item["quote"]],
                    "evidence": [
                        {
                            "claim": (
                                f'{item["name"]}: {item["value"]}'
                            ),
                            "quote": item["quote"],
                            "relevance_status": "Подтверждает",
                            "relevance_explanation": (
                                "Тестовая проверка соответствия."
                            ),
                        }
                    ],
                    "evidence_status": "Подтверждено",
                    "rejected_quotes": [],
                }
                for item in expected
            ],
            "delivery_requirements": [],
            "document_requirements": [],
            "risks_and_uncertainties": [],
            "questions_to_customer": [],
        }

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )

    result = asyncio.run(
        analysis_service.analyze_and_save_document_requirements(
            db,
            document.id,
        )
    )

    assert result["status"] == "Завершён"
    assert result["requirements_count"] == 30
    assert result["requirements_with_source"] == 30

    analysis = db.get(TenderAnalysisDB, result["analysis_id"])
    assert analysis is not None
    assert analysis.status == "Завершён"
    assert len(analysis.result_json["technical_requirements"]) == 30

    records = (
        db.query(TenderRequirementDB)
        .filter_by(analysis_id=analysis.id)
        .all()
    )

    assert len(records) == 30
    assert all(
        record.requirement_type == "technical"
        for record in records
    )

    records_by_name = {
        record.attributes["name"]: record
        for record in records
    }
    assert len(records_by_name) == 30

    for item in expected:
        record = records_by_name[item["name"]]

        assert record.requirement_text == (
            f'{item["name"]}: {item["value"]}'
        )
        assert record.attributes["value"] == item["value"]
        assert (
            record.attributes["is_required"]
            is item["is_required"]
        )
        assert record.source_chunk_id == first_chunk.id
        assert record.extraction_status == "Источник найден"
        assert record.evidence_quote == item["quote"]
        assert (
            record.attributes["semantic_evidence_status"]
            == "Подтверждено"
        )
        assert (
            record.attributes["evidence"][0]["relevance_status"]
            == "Подтверждает"
        )

    assert sum(
        record.attributes["is_required"] is True
        for record in records
    ) == 10
    assert sum(
        record.attributes["is_required"] is False
        for record in records
    ) == 20

def test_analyzer_error_is_saved_without_requirements(
    document_with_chunks,
    monkeypatch,
):
    db, document, _, _ = document_with_chunks

    async def failing_analyzer(document_text):
        raise RuntimeError("Тестовая ошибка Gemini")

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        failing_analyzer,
    )

    with pytest.raises(
        RuntimeError,
        match="Тестовая ошибка Gemini",
    ):
        asyncio.run(
            analysis_service.analyze_and_save_document_requirements(
                db,
                document.id,
            )
        )

    analysis = db.query(TenderAnalysisDB).filter_by(
        document_id=document.id
    ).one()

    assert analysis.status == "Ошибка"
    assert analysis.error == "Тестовая ошибка Gemini"
    assert analysis.completed_at is not None

    requirements = db.query(TenderRequirementDB).filter_by(
        analysis_id=analysis.id
    ).all()

    assert requirements == []


def _make_semantic_retry_test_result():
    return {
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
                        "claim": "Эксплуатация от -10 до +40 °C",
                        "quote": "эксплуатация при температуре от -10 до +40 °C",
                        "relevance_status": "Проверка не выполнена",
                        "relevance_explanation": "Первичная проверка не удалась.",
                        "custom_evidence_field": "keep-evidence",
                    }
                ],
                "evidence_status": "Не проверено",
                "rejected_quotes": [],
                "custom_requirement_field": {"origin": "initial"},
            }
        ],
        "delivery_requirements": [],
        "document_requirements": [],
        "risks_and_uncertainties": [],
        "questions_to_customer": [],
        "custom_top_level": {"preserve": True},
    }


def test_retry_semantic_validation_success_preserves_requirements(
    document_with_chunks,
    monkeypatch,
):
    db, document, first_chunk, _ = document_with_chunks
    extraction_calls = []
    validation_calls = []

    async def fake_analyzer(document_text):
        extraction_calls.append(document_text)
        return _make_semantic_retry_test_result()

    async def fake_validator(technical_analysis):
        validation_calls.append(True)
        technical_analysis.technical_requirements[0].evidence[0].relevance_status = (
            "Подтверждает"
        )
        technical_analysis.technical_requirements[0].evidence[0].relevance_explanation = (
            "Цитата подтверждает требование."
        )

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )
    monkeypatch.setattr(
        analysis_service,
        "validate_evidence_relevance",
        fake_validator,
    )

    initial = asyncio.run(
        analysis_service.analyze_and_save_document_requirements(
            db,
            document.id,
        )
    )
    analysis_id = initial["analysis_id"]

    analysis = db.get(TenderAnalysisDB, analysis_id)
    assert analysis.status == "Завершён"
    assert analysis.semantic_validation_status == "Не выполнена"

    records_before = (
        db.query(TenderRequirementDB)
        .filter_by(analysis_id=analysis_id)
        .order_by(TenderRequirementDB.id)
        .all()
    )
    assert len(records_before) == 1
    original_ids = [record.id for record in records_before]
    original_chunk_ids = [record.source_chunk_id for record in records_before]
    assert original_chunk_ids == [first_chunk.id]

    retried = asyncio.run(
        analysis_service.retry_semantic_validation(
            db,
            document.id,
            analysis_id,
        )
    )

    assert retried["semantic_validation_status"] == "Завершена"
    assert retried["retried_evidence_count"] == 1
    assert len(extraction_calls) == 1
    assert len(validation_calls) == 1

    db.expire_all()
    analysis = db.get(TenderAnalysisDB, analysis_id)
    records_after = (
        db.query(TenderRequirementDB)
        .filter_by(analysis_id=analysis_id)
        .order_by(TenderRequirementDB.id)
        .all()
    )

    assert analysis.status == "Завершён"
    assert analysis.semantic_validation_status == "Завершена"
    assert analysis.result_json["technical_requirements"][0]["evidence"][0][
        "relevance_status"
    ] == "Подтверждает"
    assert analysis.result_json["custom_top_level"] == {"preserve": True}
    assert analysis.result_json["technical_requirements"][0][
        "custom_requirement_field"
    ] == {"origin": "initial"}
    assert analysis.result_json["technical_requirements"][0]["evidence"][0][
        "custom_evidence_field"
    ] == "keep-evidence"

    assert [record.id for record in records_after] == original_ids
    assert records_after[0].attributes["custom_requirement_field"] == {
        "origin": "initial"
    }
    assert [record.source_chunk_id for record in records_after] == original_chunk_ids
    assert records_after[0].attributes["evidence"][0]["relevance_status"] == (
        "Подтверждает"
    )
    assert records_after[0].attributes["semantic_evidence_status"] == (
        "Подтверждено"
    )

    no_op = asyncio.run(
        analysis_service.retry_semantic_validation(
            db,
            document.id,
            analysis_id,
        )
    )
    assert no_op["retried_evidence_count"] == 0
    assert len(validation_calls) == 1
    assert len(extraction_calls) == 1


def test_retry_semantic_validation_failure_keeps_extraction_and_requirements(
    document_with_chunks,
    monkeypatch,
):
    db, document, first_chunk, _ = document_with_chunks
    extraction_calls = []

    async def fake_analyzer(document_text):
        extraction_calls.append(document_text)
        return _make_semantic_retry_test_result()

    async def fake_validator(technical_analysis):
        evidence = technical_analysis.technical_requirements[0].evidence[0]
        evidence.relevance_status = "Проверка не выполнена"
        evidence.relevance_explanation = "Повторная проверка не удалась."

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )
    monkeypatch.setattr(
        analysis_service,
        "validate_evidence_relevance",
        fake_validator,
    )

    initial = asyncio.run(
        analysis_service.analyze_and_save_document_requirements(
            db,
            document.id,
        )
    )
    analysis_id = initial["analysis_id"]

    before = (
        db.query(TenderRequirementDB)
        .filter_by(analysis_id=analysis_id)
        .one()
    )
    original_id = before.id
    original_chunk_id = before.source_chunk_id

    retried = asyncio.run(
        analysis_service.retry_semantic_validation(
            db,
            document.id,
            analysis_id,
        )
    )

    db.expire_all()
    analysis = db.get(TenderAnalysisDB, analysis_id)
    after = (
        db.query(TenderRequirementDB)
        .filter_by(analysis_id=analysis_id)
        .one()
    )

    assert retried["semantic_validation_status"] == "Не выполнена"
    assert retried["retried_evidence_count"] == 1
    assert analysis.status == "Завершён"
    assert analysis.semantic_validation_status == "Не выполнена"
    assert after.id == original_id
    assert after.source_chunk_id == original_chunk_id == first_chunk.id
    assert after.attributes["evidence"][0]["relevance_status"] == (
        "Проверка не выполнена"
    )
    assert len(extraction_calls) == 1
