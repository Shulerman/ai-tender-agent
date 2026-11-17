import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.database import SessionLocal
from app.commercial.models import SupplierDB
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
