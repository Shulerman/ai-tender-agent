import uuid

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import SessionLocal, TenderDB
from app.documents.models import TenderDocumentDB, TenderAnalysisDB
from app.commercial.models import (
    CommercialAnalysisDB,
    CommercialMatchRunDB,
    CommercialMatchDB,
)
from app.commercial.service import create_commercial_analysis


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
        main_module.app.dependency_overrides.pop(main_module.get_db, None)


@pytest.fixture
def scenario(db):
    suffix = uuid.uuid4().hex

    tender = TenderDB(
        tender_id=f"FULL-ANALYSIS-{suffix}",
        title="Тест полного анализа",
    )
    db.add(tender)
    db.commit()
    db.refresh(tender)

    commercial = create_commercial_analysis(
        db,
        {"tender_id": tender.tender_id},
    )

    document = TenderDocumentDB(
        document_uuid=str(uuid.uuid4()),
        tender_id=tender.id,
        original_name="full_analysis_test.html",
        file_path="full_analysis_test.html",
        file_hash=None,
        detected_extension=".html",
        size_bytes=100,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    yield tender, commercial, document

    db.query(CommercialMatchDB).filter(
        CommercialMatchDB.analysis_id == commercial.id
    ).delete(synchronize_session=False)

    db.query(CommercialMatchRunDB).filter(
        CommercialMatchRunDB.commercial_analysis_id == commercial.id
    ).delete(synchronize_session=False)

    db.query(TenderAnalysisDB).filter(
        TenderAnalysisDB.document_id == document.id
    ).delete(synchronize_session=False)

    db.query(TenderDocumentDB).filter(
        TenderDocumentDB.id == document.id
    ).delete(synchronize_session=False)

    db.query(CommercialAnalysisDB).filter(
        CommercialAnalysisDB.id == commercial.id
    ).delete(synchronize_session=False)

    db.query(TenderDB).filter(
        TenderDB.id == tender.id
    ).delete(synchronize_session=False)

    db.commit()


def test_full_analysis_rejects_request_when_gemini_is_disabled(
    client,
    db,
    scenario,
    monkeypatch,
):
    _, commercial, document = scenario
    called = False

    async def forbidden_analyzer(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("Анализ не должен запускаться")

    monkeypatch.setattr(main_module, "is_gemini_enabled", lambda: False)
    monkeypatch.setattr(
        main_module,
        "analyze_and_save_document_requirements",
        forbidden_analyzer,
    )

    response = client.post(
        f"/documents/{document.id}/full-analysis",
        json={"commercial_analysis_id": commercial.id},
    )

    assert response.status_code == 503
    assert called is False


def test_full_analysis_runs_both_stages(
    client,
    db,
    scenario,
    monkeypatch,
):
    _, commercial, document = scenario

    async def fake_analyzer(db, document_id):
        analysis = TenderAnalysisDB(
            document_id=document_id,
            analysis_type="technical_requirements",
            status="Завершён",
            result_json={"products": []},
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        return {
            "analysis_id": analysis.id,
            "document_id": document_id,
            "status": "Завершён",
            "requirements_count": 0,
            "requirements_with_source": 0,
            "result": {"products": []},
        }

    monkeypatch.setattr(main_module, "is_gemini_enabled", lambda: True)
    monkeypatch.setattr(
        main_module,
        "analyze_and_save_document_requirements",
        fake_analyzer,
    )

    response = client.post(
        f"/documents/{document.id}/full-analysis",
        json={"commercial_analysis_id": commercial.id},
    )

    assert response.status_code == 200
    result = response.json()

    assert result["document_analysis"]["status"] == "Завершён"
    assert result["document_analysis"]["analysis_id"] is not None

    match_run = result["commercial_match_run"]
    assert match_run["commercial_analysis_id"] == commercial.id
    assert match_run["tender_analysis_id"] == result["document_analysis"]["analysis_id"]
    assert match_run["status"] == "Завершён"
    assert isinstance(match_run["statistics"], dict)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"commercial_analysis_id": 0},
        {"commercial_analysis_id": -1},
        {"commercial_analysis_id": "1"},
        {"commercial_analysis_id": True},
        {"commercial_analysis_id": 1, "unexpected": True},
    ],
)
def test_full_analysis_rejects_invalid_payload(
    client,
    scenario,
    monkeypatch,
    payload,
):
    _, _, document = scenario
    monkeypatch.setattr(main_module, "is_gemini_enabled", lambda: True)

    response = client.post(
        f"/documents/{document.id}/full-analysis",
        json=payload,
    )

    assert response.status_code == 422
