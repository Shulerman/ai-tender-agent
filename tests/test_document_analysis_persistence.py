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
        text="Технические требования к товару.",
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
    assert result["requirements_count"] == 1
    assert result["requirements_with_source"] == 1

    analysis = db.get(TenderAnalysisDB, result["analysis_id"])

    assert analysis is not None
    assert analysis.document_id == document.id
    assert analysis.analysis_type == "technical_requirements"
    assert analysis.status == "Завершён"
    assert analysis.completed_at is not None
    assert analysis.result_json["products"][0]["name"] == "Тестовый товар"
    assert analysis.result_json["products"][0]["attributes"][0]["name"] == "Диаметр"

    requirement = db.query(TenderRequirementDB).filter_by(
        analysis_id=analysis.id
    ).one()

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
