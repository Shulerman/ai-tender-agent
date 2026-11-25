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

def test_api_returns_all_30_general_technical_requirements(
    client,
    db,
    document_with_chunks,
    monkeypatch,
):
    document, chunks = document_with_chunks

    technical_requirements = []
    quotes = []

    for number in range(1, 31):
        mandatory = number % 3 == 0
        status = "обязательно" if mandatory else "справочно"
        quote = (
            f"Параметр {number:02d}: Значение {number:02d}; "
            f"статус: {status}."
        )
        quotes.append(quote)
        technical_requirements.append({
            "name": f"Параметр {number:02d}",
            "value": f"Значение {number:02d}",
            "unit": None,
            "operator": None,
            "is_required": mandatory,
            "description": "",
            "quotes": [quote],
            "evidence": [],
            "evidence_status": "Не проверено",
            "rejected_quotes": [],
        })

    chunks[0].text = (
        chunks[0].text + "\n" + "\n".join(quotes)
    )
    db.commit()

    async def fake_analyzer(document_text):
        assert all(quote in document_text for quote in quotes)
        return {
            "products": [],
            "technical_requirements": technical_requirements,
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

    analysis_response = client.post(
        f"/documents/{document.id}/analyze"
    )
    assert analysis_response.status_code == 200
    analysis_result = analysis_response.json()
    assert analysis_result["requirements_count"] == 30
    assert analysis_result["requirements_with_source"] == 30

    response = client.get(
        f"/documents/{document.id}/requirements",
        params={"analysis_id": analysis_result["analysis_id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document.id
    assert payload["analysis_id"] == analysis_result["analysis_id"]

    records = payload["requirements"]
    assert len(records) == 30

    for number, record in enumerate(records, start=1):
        mandatory = number % 3 == 0
        status = "обязательно" if mandatory else "справочно"
        expected_quote = (
            f"Параметр {number:02d}: Значение {number:02d}; "
            f"статус: {status}."
        )

        assert record["requirement_type"] == "technical"
        assert record["requirement_text"] == (
            f"Параметр {number:02d}: Значение {number:02d}"
        )
        assert record["attributes"]["name"] == f"Параметр {number:02d}"
        assert record["attributes"]["value"] == f"Значение {number:02d}"
        assert record["attributes"]["is_required"] is mandatory
        assert record["attributes"]["semantic_evidence_status"] == "Не проверено"
        assert record["source_chunk_id"] == chunks[0].id
        assert record["evidence_quote"] == expected_quote
        assert record["extraction_status"] == "Источник найден"
        assert record["confidence"] is None


def _api_semantic_retry_result():
    quote = "Технические требования к тестовому товару."
    return {
        "products": [],
        "technical_requirements": [
            {
                "name": "Материал корпуса",
                "value": "Сталь",
                "unit": None,
                "operator": None,
                "is_required": True,
                "description": "",
                "quotes": [quote],
                "evidence": [
                    {
                        "claim": "Корпус изготовлен из стали",
                        "quote": quote,
                        "relevance_status": "Проверка не выполнена",
                        "relevance_explanation": "Первичная проверка не удалась.",
                    }
                ],
                "evidence_status": "Не проверено",
                "rejected_quotes": [],
            }
        ],
        "delivery_requirements": [],
        "document_requirements": [],
        "risks_and_uncertainties": [],
        "questions_to_customer": [],
    }


def test_retry_semantic_validation_api_success(
    client,
    db,
    document_with_chunks,
    monkeypatch,
):
    document, chunks = document_with_chunks
    extraction_calls = []
    validation_calls = []

    async def fake_analyzer(document_text):
        extraction_calls.append(document_text)
        return _api_semantic_retry_result()

    async def fake_validator(technical_analysis):
        validation_calls.append(True)
        evidence = technical_analysis.technical_requirements[0].evidence[0]
        evidence.relevance_status = "Подтверждает"
        evidence.relevance_explanation = "Цитата подтверждает требование."

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

    analysis_response = client.post(
        f"/documents/{document.id}/analyze"
    )
    assert analysis_response.status_code == 200
    analysis_id = analysis_response.json()["analysis_id"]

    before_response = client.get(
        f"/documents/{document.id}/requirements",
        params={"analysis_id": analysis_id},
    )
    assert before_response.status_code == 200
    before_records = before_response.json()["requirements"]
    assert len(before_records) == 1

    original_id = before_records[0]["id"]
    original_chunk_id = before_records[0]["source_chunk_id"]
    assert original_chunk_id == chunks[0].id

    async def extraction_must_not_run(document_text):
        raise AssertionError("Retry must not run document extraction")

    monkeypatch.setattr(
        analysis_service,
        "analyze_technical_requirements",
        extraction_must_not_run,
    )

    retry_response = client.post(
        f"/documents/{document.id}/analyses/{analysis_id}/retry-semantic-validation"
    )

    assert retry_response.status_code == 200
    retry_payload = retry_response.json()
    assert retry_payload["analysis_id"] == analysis_id
    assert retry_payload["document_id"] == document.id
    assert retry_payload["semantic_validation_status"] == "Завершена"
    assert retry_payload["retried_evidence_count"] == 1
    assert len(extraction_calls) == 1
    assert len(validation_calls) == 1

    after_response = client.get(
        f"/documents/{document.id}/requirements",
        params={"analysis_id": analysis_id},
    )
    assert after_response.status_code == 200
    after_records = after_response.json()["requirements"]

    assert len(after_records) == 1
    assert after_records[0]["id"] == original_id
    assert after_records[0]["source_chunk_id"] == original_chunk_id
    assert after_records[0]["attributes"]["evidence"][0][
        "relevance_status"
    ] == "Подтверждает"
    assert after_records[0]["attributes"]["semantic_evidence_status"] == (
        "Подтверждено"
    )


def test_retry_semantic_validation_api_rejects_unknown_analysis(
    client,
    document_with_chunks,
):
    document, _ = document_with_chunks

    response = client.post(
        f"/documents/{document.id}/analyses/999999999/retry-semantic-validation"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Анализ не найден"


def test_retry_semantic_validation_api_rejects_incomplete_analysis(
    client,
    db,
    document_with_chunks,
):
    document, _ = document_with_chunks

    analysis = TenderAnalysisDB(
        document_id=document.id,
        analysis_type="technical_requirements",
        status="Выполняется",
        result_json={},
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    response = client.post(
        f"/documents/{document.id}/analyses/{analysis.id}/retry-semantic-validation"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Основной анализ ещё не завершён"
