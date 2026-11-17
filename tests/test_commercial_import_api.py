from datetime import datetime
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.database import SessionLocal
from app.commercial.models import (
    SupplierDB,
    ProductDB,
    PriceListImportRowDB,
    SupplierOfferDB,
)
from app import main as main_module


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

    main_module.app.dependency_overrides[
        main_module.get_db
    ] = override_get_db

    with TestClient(main_module.app) as test_client:
        yield test_client

    main_module.app.dependency_overrides.clear()


def create_excel():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Прайс"

    worksheet.append([
        "Артикул",
        "Наименование",
        "Цена",
        "Валюта",
        "Ед. изм.",
    ])
    worksheet.append([
        "API-001",
        "Тестовый товар API",
        150,
        "RUB",
        "шт.",
    ])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def test_excel_preview_api(client):
    response = client.post(
        "/commercial/imports/excel/preview",
        files={
            "file": (
                "api_prices.xlsx",
                create_excel(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={
            "header_row": "1",
            "sheet_name": "Прайс",
        },
    )

    assert response.status_code == 200
    result = response.json()

    assert result["preview"]["selected_sheet"] == "Прайс"
    assert "Наименование" in result["preview"]["headers"]


def test_excel_import_api(client, db, tmp_path, monkeypatch):
    supplier = SupplierDB(
        name=f"API тестовый поставщик {uuid.uuid4().hex}"
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)

    monkeypatch.setattr(
        main_module,
        "COMMERCIAL_PRICE_LISTS_DIR",
        tmp_path,
    )

    mapping = {
        "article_number": 1,
        "name": 2,
        "price": 3,
        "currency": 4,
        "unit": 5,
    }

    response = client.post(
        "/commercial/imports/excel",
        data={
            "supplier_id": str(supplier.id),
            "column_mapping": json.dumps(mapping, ensure_ascii=False),
            "header_row": "1",
            "sheet_name": "Прайс",
        },
        files={
            "file": (
                "api_prices.xlsx",
                create_excel(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()

    assert result["original_name"] == "api_prices.xlsx"
    assert result["file_hash"]
    assert result["result"]["import_id"] is not None
    assert result["result"]["total_rows"] == 1

def create_unmatched_import(client, db, tmp_path, monkeypatch):
    supplier = SupplierDB(
        name=f"API ручное сопоставление {uuid.uuid4().hex}"
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)

    monkeypatch.setattr(
        main_module,
        "COMMERCIAL_PRICE_LISTS_DIR",
        tmp_path,
    )

    mapping = {
        "article_number": 1,
        "name": 2,
        "price": 3,
        "currency": 4,
        "unit": 5,
    }

    response = client.post(
        "/commercial/imports/excel",
        data={
            "supplier_id": str(supplier.id),
            "column_mapping": json.dumps(mapping, ensure_ascii=False),
            "header_row": "1",
            "sheet_name": "Прайс",
        },
        files={
            "file": (
                "unmatched_prices.xlsx",
                create_excel(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200

    import_id = response.json()["result"]["import_id"]

    import_row = db.query(PriceListImportRowDB).filter_by(
        import_id=import_id
    ).one()

    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None

    return supplier, import_id, import_row


def test_get_unmatched_import_rows_api(
    client,
    db,
    tmp_path,
    monkeypatch,
):
    supplier, import_id, import_row = create_unmatched_import(
        client,
        db,
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        f"/commercial/imports/{import_id}/unmatched"
    )

    assert response.status_code == 200

    result = response.json()

    assert result["import_id"] == import_id
    assert result["count"] == 1
    assert len(result["rows"]) == 1

    row = result["rows"][0]

    assert row["row_id"] == import_row.id
    assert row["source_row"] == 2
    assert row["article_number"] == "API-001"
    assert row["name"] == "Тестовый товар API"
    assert row["price"] == 150
    assert row["currency"] == "RUB"
    assert row["unit"] == "шт."
    assert row["status"] == "Требует сопоставления"


def test_manual_match_api(
    client,
    db,
    tmp_path,
    monkeypatch,
):
    supplier, import_id, import_row = create_unmatched_import(
        client,
        db,
        tmp_path,
        monkeypatch,
    )

    product = ProductDB(
        name=f"Товар для ручного сопоставления {uuid.uuid4().hex}",
        article_number="MANUAL-API-001",
        created_at=datetime.now(),
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    response = client.post(
        f"/commercial/imports/{import_id}/rows/{import_row.id}/match",
        json={"product_id": product.id},
    )

    assert response.status_code == 200

    result = response.json()["result"]

    assert result["import_id"] == import_id
    assert result["row_id"] == import_row.id
    assert result["product_id"] == product.id
    assert result["status"] == "Сопоставлен"

    db.refresh(import_row)

    assert import_row.product_id == product.id
    assert import_row.status == "Сопоставлен"

    offer = db.query(SupplierOfferDB).filter_by(
        import_id=import_id,
        product_id=product.id,
    ).one()

    assert offer.supplier_id == supplier.id
    assert offer.price == 150
    assert offer.currency == "RUB"
    assert offer.verification_status == "Не проверено"


def test_manual_match_api_rejects_repeated_match(
    client,
    db,
    tmp_path,
    monkeypatch,
):
    _, import_id, import_row = create_unmatched_import(
        client,
        db,
        tmp_path,
        monkeypatch,
    )

    product = ProductDB(
        name=f"Товар для проверки повтора {uuid.uuid4().hex}",
        article_number="MANUAL-API-002",
        created_at=datetime.now(),
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    url = (
        f"/commercial/imports/{import_id}"
        f"/rows/{import_row.id}/match"
    )

    first_response = client.post(
        url,
        json={"product_id": product.id},
    )

    second_response = client.post(
        url,
        json={"product_id": product.id},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409

    offers = db.query(SupplierOfferDB).filter_by(
        import_id=import_id,
        product_id=product.id,
    ).all()

    assert len(offers) == 1