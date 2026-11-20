from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import SessionLocal, TenderDB
from app.documents import storage as storage_module
from app.documents.models import TenderDocumentDB, DocumentChunkDB


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
def html_content():
    return (
        "<!doctype html><html><body>"
        "<h1>Технические требования</h1>"
        "<p>Поставка 10 единиц товара.</p>"
        "</body></html>"
    ).encode("utf-8")


def test_document_upload_saves_document_and_chunks(
    client, db, tmp_path, monkeypatch, html_content
):
    monkeypatch.setattr(storage_module, "DOCUMENTS_DIR", tmp_path)

    tender = TenderDB(
        tender_id=f"DOCUMENT-API-{uuid.uuid4().hex}",
        title="Тестовый тендер для загрузки документа",
    )
    db.add(tender)
    db.commit()
    db.refresh(tender)

    response = client.post(
        "/documents/upload",
        data={"tender_id": str(tender.id)},
        files={
            "file": (
                "requirements.html",
                html_content,
                "text/html",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()

    assert result["message"] == "Документ успешно загружен и обработан"
    assert result["document_id"]
    assert result["database_id"]
    assert result["chunks_count"] == 2
    assert result["original_name"] == "requirements.html"
    assert result["detected_extension"] == ".html"
    assert result["size_bytes"] == len(html_content)
    assert result["text_length"] > 0
    assert "Технические требования" in result["text"]
    assert "Поставка 10 единиц товара" in result["text"]

    document = db.query(TenderDocumentDB).filter_by(
        document_uuid=result["document_id"]
    ).one()

    assert document.id == result["database_id"]
    assert document.tender_id == tender.id
    assert document.original_name == "requirements.html"
    assert Path(document.file_path).exists()

    chunks = (
        db.query(DocumentChunkDB)
        .filter_by(document_id=document.id)
        .order_by(DocumentChunkDB.sequence_number)
        .all()
    )

    assert len(chunks) == 2
    assert [chunk.sequence_number for chunk in chunks] == [1, 2]
    assert chunks[0].locator_type == "paragraph"
    assert "Технические требования" in chunks[0].text
    assert "Поставка 10 единиц товара" in chunks[1].text


def test_document_upload_rejects_unknown_tender(
    client, db, tmp_path, monkeypatch, html_content
):
    monkeypatch.setattr(storage_module, "DOCUMENTS_DIR", tmp_path)

    documents_before = db.query(TenderDocumentDB).count()

    response = client.post(
        "/documents/upload",
        data={"tender_id": "999999999"},
        files={
            "file": (
                "must_not_be_saved.html",
                html_content,
                "text/html",
            )
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Тендер не найден"
    assert db.query(TenderDocumentDB).count() == documents_before
    assert not list(tmp_path.iterdir())
