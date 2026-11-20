import uuid

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import SessionLocal
from app.documents import analysis_service
from app.documents.models import (
    DocumentChunkDB,
    TenderAnalysisDB,
    TenderDocumentDB,
    TenderRequirementDB,
)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    main_module.app.dependency_overrides[main_module.get_db] = override_get_db

    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        main_module.app.dependency_overrides.clear()


@pytest.fixture
def document_with_chunks(db):
    document = TenderDocumentDB(
        document_uuid=str(uuid.uuid4()),
        original_name="api_requirements.html",
        file_path="api_requirements.html",
        file_hash=None,
        detected_extension=".html",
        size_bytes=100,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    chunks = [
        DocumentChunkDB(
            document_id=document.id,
            sequence_number=1,
            locator_type="paragraph",
            locator_value="1",
            text="Технические требования к тестовому товару.",
        ),
        DocumentChunkDB(
            document_id=document.id,
            sequence_number=2,
            locator_type="paragraph",
            locator_value="2",
            text="Поставка товара в течение 10 рабочих дней.",
        ),
    ]
    db.add_all(chunks)
    db.commit()

    for chunk in chunks:
        db.refresh(chunk)

    try:
        yield document, chunks
    finally:
        db.query(TenderRequirementDB).filter_by(
            document_id=document.id
        ).delete(synchronize_session=False)
        db.query(TenderAnalysisDB).filter_by(
            document_id=document.id
        ).delete(synchronize_session=False)
        db.query(DocumentChunkDB).filter_by(
            document_id=document.id
        ).delete(synchronize_session=False)
        db.query(TenderDocumentDB).filter_by(
            id=document.id
        ).delete(synchronize_session=False)
        db.commit()


def fake_analysis_result():
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
                        "evidence": [],
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


def test_analyze_document_endpoint(
    client,
    db,
    document_with_chunks,
    monkeypatch,
):
    document, chunks = document_with_chunks

    async def fake_analyzer(document_text):
        assert "Технические требования" in document_text
        assert "10 рабочих дней" in document_text
        return fake_analysis_result()

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )

    response = client.post(
        f"/documents/{document.id}/analyze"
    )

    assert response.status_code == 200
    result = response.json()

    assert result["document_id"] == document.id
    assert result["status"] == "Завершён"
    assert result["requirements_count"] == 1
    assert result["requirements_with_source"] == 1
    assert result["analysis_id"] is not None

    analysis = db.get(TenderAnalysisDB, result["analysis_id"])
    assert analysis is not None
    assert analysis.status == "Завершён"


def test_get_latest_document_requirements(
    client,
    db,
    document_with_chunks,
    monkeypatch,
):
    document, chunks = document_with_chunks

    async def fake_analyzer(document_text):
        return fake_analysis_result()

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )

    analysis_response = client.post(
        f"/documents/{document.id}/analyze"
    )
    assert analysis_response.status_code == 200

    response = client.get(
        f"/documents/{document.id}/requirements"
    )

    assert response.status_code == 200
    result = response.json()

    assert result["document_id"] == document.id
    assert result["analysis_id"] == analysis_response.json()["analysis_id"]
    assert len(result["requirements"]) == 1

    requirement = result["requirements"][0]
    assert requirement["requirement_type"] == "product"
    assert requirement["requirement_text"] == "Тестовый товар"
    assert requirement["source_chunk_id"] == chunks[1].id
    assert requirement["evidence_quote"] == (
        "Поставка товара в течение 10 рабочих дней."
    )
    assert requirement["confidence"] is None
    assert requirement["extraction_status"] == "Источник найден"
    assert requirement["attributes"]["attributes"][0]["name"] == "Диаметр"
    assert requirement["attributes"]["attributes"][0]["value"] == "20"
    assert requirement["attributes"]["attributes"][0]["unit"] == "мм"
    assert requirement["attributes"]["attributes"][0]["operator"] == ">="
    assert requirement["attributes"]["attributes"][0]["is_required"] is True
    assert requirement["attributes"]["attributes"][0]["evidence"] == []


def test_get_requirements_by_analysis_id(
    client,
    document_with_chunks,
    monkeypatch,
):
    document, _ = document_with_chunks

    async def fake_analyzer(document_text):
        return fake_analysis_result()

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        fake_analyzer,
    )

    first = client.post(f"/documents/{document.id}/analyze")
    second = client.post(f"/documents/{document.id}/analyze")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["analysis_id"] != second.json()["analysis_id"]

    response = client.get(
        f"/documents/{document.id}/requirements",
        params={"analysis_id": first.json()["analysis_id"]},
    )

    assert response.status_code == 200
    assert response.json()["analysis_id"] == first.json()["analysis_id"]


def test_requirements_reject_analysis_from_another_document(
    client,
    db,
    document_with_chunks,
    monkeypatch,
):
    document, _ = document_with_chunks

    other_document = TenderDocumentDB(
        document_uuid=str(uuid.uuid4()),
        original_name="other.html",
        file_path="other.html",
        file_hash=None,
        detected_extension=".html",
        size_bytes=10,
    )
    db.add(other_document)
    db.commit()
    db.refresh(other_document)

    try:
        other_analysis = TenderAnalysisDB(
            document_id=other_document.id,
            analysis_type="technical_requirements",
            status="Завершён",
            result_json={},
        )
        db.add(other_analysis)
        db.commit()
        db.refresh(other_analysis)

        response = client.get(
            f"/documents/{document.id}/requirements",
            params={"analysis_id": other_analysis.id},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Завершённый анализ не найден"
    finally:
        db.query(TenderAnalysisDB).filter_by(
            document_id=other_document.id
        ).delete(synchronize_session=False)
        db.query(TenderDocumentDB).filter_by(
            id=other_document.id
        ).delete(synchronize_session=False)
        db.commit()
