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
    ManufacturerDB,
    PriceListImportDB,
    PriceListImportRowDB,
    SupplierOfferDB,
    SupplierOfferVerificationDB,
    ProductDuplicateReviewDB,
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


def create_excel(article_number="API-001", product_name="Тестовый товар API", price=150):
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
        article_number,
        product_name,
        price,
        "RUB",
        "шт.",
    ])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()



def test_excel_import_end_to_end(
    client, db, tmp_path, monkeypatch
):
    supplier = SupplierDB(name=f"E2E supplier {uuid.uuid4().hex}")
    article = f"E2E-{uuid.uuid4().hex}"
    known_product = ProductDB(
        name=f"Known {article}",
        article_number=article,
        created_at=datetime.now(),
    )
    db.add_all([supplier, known_product])
    db.commit()
    db.refresh(supplier)
    db.refresh(known_product)

    monkeypatch.setattr(
        main_module, "COMMERCIAL_PRICE_LISTS_DIR", tmp_path
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Прайс"
    sheet.append(["Артикул", "Наименование", "Цена", "Валюта", "Ед. изм."])
    sheet.append([article, known_product.name, 150, "RUB", "шт."])
    sheet.append(["UNKNOWN-E2E", "Новый товар", 275, "RUB", "шт."])
    buffer = io.BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()

    mapping = {
        "article_number": 1, "name": 2, "price": 3,
        "currency": 4, "unit": 5,
    }

    def upload():
        return client.post(
            "/commercial/imports/excel",
            data={
                "supplier_id": str(supplier.id),
                "column_mapping": json.dumps(mapping, ensure_ascii=False),
                "header_row": "1",
                "sheet_name": "Прайс",
            },
            files={"file": (
                "e2e.xlsx", content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
        )

    first_response = upload()
    assert first_response.status_code == 200
    first_id = first_response.json()["result"]["import_id"]

    rows = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=first_id)
        .order_by(PriceListImportRowDB.source_row)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].product_id == known_product.id
    assert rows[1].product_id is None
    unmatched_row_id = rows[1].id

    unmatched = client.get(
        f"/commercial/imports/{first_id}/unmatched"
    )
    assert unmatched.status_code == 200
    assert unmatched.json()["count"] == 1
    assert unmatched.json()["rows"][0]["row_id"] == unmatched_row_id

    manual_product = ProductDB(
        name=f"Manual target {uuid.uuid4().hex}",
        article_number=f"MANUAL-{uuid.uuid4().hex}",
        created_at=datetime.now(),
    )
    db.add(manual_product)
    db.commit()
    db.refresh(manual_product)

    matched = client.post(
        f"/commercial/imports/{first_id}/rows/{unmatched_row_id}/match",
        json={"product_id": manual_product.id},
    )
    assert matched.status_code == 200
    db.refresh(rows[1])
    assert rows[1].product_id == manual_product.id

    first_offers = (
        db.query(SupplierOfferDB)
        .filter_by(supplier_id=supplier.id, import_id=first_id)
        .all()
    )
    assert len(first_offers) == 2

    second_response = upload()
    assert second_response.status_code == 200
    second_id = second_response.json()["result"]["import_id"]
    assert second_id != first_id

    second_rows = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=second_id)
        .order_by(PriceListImportRowDB.source_row)
        .all()
    )
    assert len(second_rows) == 2
    assert [row.product_id for row in second_rows] == [
        known_product.id, manual_product.id
    ]
    assert all(row.status == "Сопоставлен" for row in second_rows)

    offers = (
        db.query(SupplierOfferDB)
        .filter(
            SupplierOfferDB.supplier_id == supplier.id,
            SupplierOfferDB.import_id.in_([first_id, second_id]),
        )
        .all()
    )
    assert len(offers) == 4
    assert sorted(offer.price for offer in offers) == [150, 150, 275, 275]

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

def test_reimport_same_excel_preserves_offer_history(
    client,
    db,
    tmp_path,
    monkeypatch,
):
    supplier = SupplierDB(
        name=f"API повторный импорт {uuid.uuid4().hex}"
    )
    unique_article = f"API-{uuid.uuid4().hex}"
    product_name = f"Товар {unique_article}"
    product = ProductDB(
        name=product_name,
        article_number=unique_article,
        created_at=datetime.now(),
    )
    db.add_all([supplier, product])
    db.commit()
    db.refresh(supplier)
    db.refresh(product)

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
    file_content = create_excel(
        article_number=unique_article,
        product_name=product_name,
        price=150,
    )
    changed_file_content = create_excel(
        article_number=unique_article,
        product_name=product_name,
        price=175,
    )
    url = "/commercial/imports/excel"

    def upload(content):
        return client.post(
            url,
            data={
                "supplier_id": str(supplier.id),
                "column_mapping": json.dumps(
                    mapping,
                    ensure_ascii=False,
                ),
                "header_row": "1",
                "sheet_name": "Прайс",
            },
            files={
                "file": (
                    "api_prices.xlsx",
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    first_response = upload(file_content)
    second_response = upload(file_content)
    third_response = upload(changed_file_content)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert third_response.status_code == 200

    first = first_response.json()
    second = second_response.json()
    third = third_response.json()

    assert first["file_hash"] == second["file_hash"]
    assert first["file_hash"] != third["file_hash"]

    import_ids = [
        first["result"]["import_id"],
        second["result"]["import_id"],
        third["result"]["import_id"],
    ]
    assert len(set(import_ids)) == 3

    imports = (
        db.query(PriceListImportDB)
        .filter(PriceListImportDB.id.in_(import_ids))
        .all()
    )
    assert len(imports) == 3

    offers = (
        db.query(SupplierOfferDB)
        .filter(
            SupplierOfferDB.supplier_id == supplier.id,
            SupplierOfferDB.product_id == product.id,
            SupplierOfferDB.import_id.in_(import_ids),
        )
        .order_by(SupplierOfferDB.import_id)
        .all()
    )

    assert len(offers) == 3
    assert [offer.price for offer in offers] == [150, 150, 175]


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

def test_manual_match_api_rejects_missing_product_id(
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

    response = client.post(
        f"/commercial/imports/{import_id}/rows/{import_row.id}/match",
        json={},
    )

    assert response.status_code == 422

    db.refresh(import_row)
    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None


def test_manual_match_api_rejects_nonexistent_product(
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

    response = client.post(
        f"/commercial/imports/{import_id}/rows/{import_row.id}/match",
        json={"product_id": 999999999},
    )

    assert response.status_code == 404

    db.refresh(import_row)
    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None


def test_search_products_api_returns_manufacturer_and_product_details(client, db):
    token = uuid.uuid4().hex

    manufacturer = ManufacturerDB(
        name=f"Производитель {token}",
        country="Россия",
    )
    db.add(manufacturer)
    db.flush()

    product_with_manufacturer = ProductDB(
        name=f"Товар с производителем {token}",
        article_number=f"WITH-{token}",
        manufacturer_id=manufacturer.id,
        unit="шт.",
        category="Оборудование",
        created_at=datetime.now(),
    )

    product_without_manufacturer = ProductDB(
        name=f"Товар без производителя {token}",
        article_number=f"WITHOUT-{token}",
        unit="кг",
        category="Материалы",
        created_at=datetime.now(),
    )

    db.add_all([
        product_with_manufacturer,
        product_without_manufacturer,
    ])
    db.commit()

    response = client.get(
        "/commercial/products/search",
        params={"q": token},
    )

    assert response.status_code == 200

    results = {
        item["id"]: item
        for item in response.json()["products"]
    }

    with_manufacturer = results[product_with_manufacturer.id]
    without_manufacturer = results[product_without_manufacturer.id]

    assert with_manufacturer["manufacturer"] == manufacturer.name
    assert with_manufacturer["manufacturer_country"] == "Россия"
    assert with_manufacturer["unit"] == "шт."
    assert with_manufacturer["category"] == "Оборудование"

    assert without_manufacturer["manufacturer"] is None
    assert without_manufacturer["manufacturer_country"] is None
    assert without_manufacturer["unit"] == "кг"
    assert without_manufacturer["category"] == "Материалы"


def test_search_products_api_rejects_query_longer_than_500_characters(client):
    response = client.get(
        "/commercial/products/search",
        params={"q": "x" * 501},
    )

    assert response.status_code == 422


def test_search_products_api_prioritizes_exact_matches(client, db):
    token = uuid.uuid4().hex
    exact_name = f"Насос {token}"

    partial_product = ProductDB(
        name=f"Промышленный {exact_name}",
        article_number=f"PARTIAL-{token}",
        unit="шт.",
        created_at=datetime.now(),
    )

    exact_product = ProductDB(
        name=exact_name,
        article_number=f"EXACT-{token}",
        unit="шт.",
        created_at=datetime.now(),
    )

    # Частичный результат добавляем первым.
    db.add(partial_product)
    db.add(exact_product)
    db.commit()

    response = client.get(
        "/commercial/products/search",
        params={"q": exact_name},
    )

    assert response.status_code == 200

    results = response.json()["products"]

    assert len(results) >= 2
    assert results[0]["id"] == exact_product.id
    assert results[1]["id"] == partial_product.id

def test_manual_match_api_rejects_invalid_product_id_type(
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

    response = client.post(
        f"/commercial/imports/{import_id}/rows/{import_row.id}/match",
        json={"product_id": "123"},
    )

    assert response.status_code == 422

    db.refresh(import_row)
    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None


def test_manual_match_api_rejects_missing_price(
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

    import_row.price = None
    db.commit()

    product = ProductDB(
        name=f"Товар без цены {uuid.uuid4().hex}",
        article_number=f"NO-PRICE-{uuid.uuid4().hex}",
        created_at=datetime.now(),
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    response = client.post(
        f"/commercial/imports/{import_id}/rows/{import_row.id}/match",
        json={"product_id": product.id},
    )

    assert response.status_code == 400
    assert "отсутствует цена" in response.json()["detail"]

    db.refresh(import_row)
    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None

    offers_count = db.query(SupplierOfferDB).filter_by(
        supplier_id=supplier.id,
        product_id=product.id,
    ).count()
    assert offers_count == 0


def test_manual_match_api_rejects_row_from_another_import(
    client,
    db,
    tmp_path,
    monkeypatch,
):
    _, first_import_id, _ = create_unmatched_import(
        client,
        db,
        tmp_path,
        monkeypatch,
    )
    _, second_import_id, second_row = create_unmatched_import(
        client,
        db,
        tmp_path,
        monkeypatch,
    )

    assert first_import_id != second_import_id

    response = client.post(
        f"/commercial/imports/{first_import_id}/rows/{second_row.id}/match",
        json={"product_id": 1},
    )

    assert response.status_code == 404
    assert "Строка не найдена" in response.json()["detail"]

    db.refresh(second_row)
    assert second_row.status == "Требует сопоставления"
    assert second_row.product_id is None


def test_product_duplicates_api_groups_exact_matches(client, db):
    token = uuid.uuid4().hex

    manufacturer_a = ManufacturerDB(name=f"Производитель A {token}")
    manufacturer_b = ManufacturerDB(name=f"Производитель B {token}")
    db.add_all([manufacturer_a, manufacturer_b])
    db.flush()

    products = [
        ProductDB(
            name=f"Товар ё {token}",
            article_number=f"AB-001-{token}",
            manufacturer_id=manufacturer_a.id,
        ),
        ProductDB(
            name=f" ТОВАР е {token} ",
            article_number=f" ab-001-{token} ",
            manufacturer_id=manufacturer_a.id,
        ),
        ProductDB(
            name=f"Другой товар {token}",
            article_number=f"AB-001-{token}",
            manufacturer_id=manufacturer_b.id,
        ),
        ProductDB(
            name=f"Товар с тем же артикулом без производителя {token}",
            article_number=f"AB-001-{token}",
        ),
        ProductDB(
            name=f"Товар без производителя 1 {token}",
            article_number=f"NO-MFR-{token}",
        ),
        ProductDB(
            name=f"Товар без производителя 2 {token}",
            article_number=f" no-mfr-{token} ",
        ),
        ProductDB(name=f"Одинаковое название {token}"),
        ProductDB(name=f" ОДИНАКОВОЕ НАЗВАНИЕ {token} "),
    ]
    db.add_all(products)
    db.commit()

    response = client.get("/commercial/products/duplicates")

    assert response.status_code == 200
    result = response.json()

    test_groups = [
        group
        for group in result["groups"]
        if token in group["match_value"]
    ]

    groups_by_type = {
        group["type"]: group
        for group in test_groups
    }

    assert len(test_groups) == 5
    assert set(groups_by_type) == {
        "duplicate_article",
        "duplicate_name",
        "article_across_manufacturers",
        "article_without_manufacturer",
        "name_without_manufacturer",
    }

    assert len(groups_by_type["duplicate_article"]["products"]) == 2
    assert len(groups_by_type["duplicate_name"]["products"]) == 2
    cross_manufacturer_products = groups_by_type[
        "article_across_manufacturers"
    ]["products"]
    assert len(cross_manufacturer_products) == 3
    assert all(
        product["manufacturer_id"] is not None
        for product in cross_manufacturer_products
    )

    assert groups_by_type["article_across_manufacturers"][
        "requires_review"
    ] is True

    assert len(
        groups_by_type["article_without_manufacturer"]["products"]
    ) == 2
    assert groups_by_type["article_without_manufacturer"][
        "requires_review"
    ] is True

    assert len(
        groups_by_type["name_without_manufacturer"]["products"]
    ) == 2
    assert groups_by_type["name_without_manufacturer"][
        "requires_review"
    ] is True
def create_api_offer(db, valid_until=None):
    token = uuid.uuid4().hex
    supplier = SupplierDB(name=f"API поставщик {token}")
    product = ProductDB(name=f"API товар {token}", unit="шт.")
    db.add_all([supplier, product])
    db.flush()

    offer = SupplierOfferDB(
        supplier_id=supplier.id,
        product_id=product.id,
        price=150,
        received_at=datetime.now(),
        valid_until=valid_until,
        source_type="manual",
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer, supplier, product


def test_commercial_offers_api_returns_current_offers(client, db):
    offer, supplier, product = create_api_offer(db)

    response = client.get("/commercial/offers")

    assert response.status_code == 200
    result = response.json()

    item = next(row for row in result if row["id"] == offer.id)
    assert item["supplier_id"] == supplier.id
    assert item["product_id"] == product.id
    assert item["supplier_name"] == supplier.name
    assert item["product_name"] == product.name
    assert item["verification_status"] == "Не проверено"
    assert float(item["price"]) == 150.0



def test_commercial_offers_api_filters_and_includes_expired(client, db):
    from datetime import timedelta

    offer_a, supplier_a, product_a = create_api_offer(db)
    offer_b, supplier_b, product_b = create_api_offer(db)
    expired_offer, _, _ = create_api_offer(
        db,
        valid_until=datetime.now() - timedelta(days=1),
    )

    response = client.get(
        "/commercial/offers",
        params={"supplier_id": supplier_a.id},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [offer_a.id]

    response = client.get(
        "/commercial/offers",
        params={"product_id": product_b.id},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [offer_b.id]

    response = client.get("/commercial/offers")
    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()}
    assert offer_a.id in returned_ids
    assert offer_b.id in returned_ids
    assert expired_offer.id in returned_ids

    expired_item = next(
        item for item in response.json()
        if item["id"] == expired_offer.id
    )
    assert expired_item["freshness_status"] == "Требуется перепроверка"
    assert expired_item["freshness_warning"] == (
        "Требуется уточнить у поставщика актуальность цены и наличия"
    )



def test_supplier_product_price_history_api_returns_all_snapshots(client, db):
    from datetime import timedelta

    offer, supplier, product = create_api_offer(db)
    now = datetime.now()

    offer.received_at = now - timedelta(days=2)
    offer.valid_until = now - timedelta(days=1)
    offer.price = 150
    offer.available_quantity = 10
    offer.verification_status = "Не проверено"

    second = SupplierOfferDB(
        supplier_id=supplier.id,
        product_id=product.id,
        price=150,
        currency="RUB",
        unit="шт.",
        received_at=now - timedelta(days=1),
        source_type="Excel",
        payment_terms="Предоплата",
        verification_status="Подтверждено",
    )
    third = SupplierOfferDB(
        supplier_id=supplier.id,
        product_id=product.id,
        price=175,
        currency="RUB",
        unit="шт.",
        received_at=now,
        source_type="Excel",
        verification_status="Не проверено",
    )
    db.add_all([second, third])
    db.commit()
    db.refresh(offer)
    db.refresh(second)
    db.refresh(third)

    unrelated_offer, _, _ = create_api_offer(db)

    response = client.get(
        f"/commercial/products/{product.id}/suppliers/{supplier.id}/price-history"
    )

    assert response.status_code == 200
    history = response.json()

    assert [item["id"] for item in history] == [
        third.id,
        second.id,
        offer.id,
    ]
    assert [float(item["price"]) for item in history] == [
        175.0,
        150.0,
        150.0,
    ]
    assert all(item["currency"] == "RUB" for item in history)
    assert history[0]["verification_status"] == "Не проверено"
    assert history[1]["verification_status"] == "Подтверждено"
    assert history[1]["source_type"] == "Excel"
    assert history[1]["payment_terms"] == "Предоплата"
    assert history[2]["available_quantity"] == 10
    assert history[2]["freshness_status"] == "Требуется перепроверка"
    assert history[2]["freshness_warning"] == (
        "Требуется уточнить у поставщика актуальность цены и наличия"
    )
    assert all(item["supplier_id"] == supplier.id for item in history)
    assert all(item["product_id"] == product.id for item in history)
    assert unrelated_offer.id not in {item["id"] for item in history}


def test_supplier_product_price_history_api_returns_404_for_missing_entities(client, db):
    offer, supplier, product = create_api_offer(db)

    missing_product = client.get(
        f"/commercial/products/99999999/suppliers/{supplier.id}/price-history"
    )
    assert missing_product.status_code == 404

    missing_supplier = client.get(
        f"/commercial/products/{product.id}/suppliers/99999999/price-history"
    )
    assert missing_supplier.status_code == 404


def test_commercial_offer_verification_api_confirms_offer(client, db):
    offer, _, _ = create_api_offer(db)

    response = client.post(
        f"/commercial/offers/{offer.id}/verification",
        json={
            "verification_status": "Подтверждено",
            "verified_by": "Тестовый пользователь",
            "notes": "Цена подтверждена поставщиком",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["verification_status"] == "Подтверждено"

    db.refresh(offer)
    assert offer.verification_status == "Подтверждено"

    history = (
        db.query(SupplierOfferVerificationDB)
        .filter(SupplierOfferVerificationDB.offer_id == offer.id)
        .all()
    )
    assert len(history) == 1
    assert history[0].verification_status == "Подтверждено"
    assert history[0].verified_by == "Тестовый пользователь"
    assert history[0].notes == "Цена подтверждена поставщиком"



def test_commercial_offer_verification_api_rejects_invalid_data(client, db):
    offer, _, _ = create_api_offer(db)

    invalid_payloads = [
        {"verification_status": "Не проверено"},
        {"verification_status": ["Подтверждено"]},
        {
            "verification_status": "Подтверждено",
            "unexpected": "value",
        },
        {
            "verification_status": "Подтверждено",
            "verified_by": 123,
        },
        {
            "verification_status": "Отклонено",
            "notes": 123,
        },
    ]

    for payload in invalid_payloads:
        response = client.post(
            f"/commercial/offers/{offer.id}/verification",
            json=payload,
        )
        assert response.status_code == 422

    db.refresh(offer)
    assert offer.verification_status == "Не проверено"

    history = (
        db.query(SupplierOfferVerificationDB)
        .filter(SupplierOfferVerificationDB.offer_id == offer.id)
        .all()
    )
    assert history == []



def test_commercial_offer_verification_api_returns_404_for_missing_offer(client):
    response = client.post(
        "/commercial/offers/999999/verification",
        json={"verification_status": "Подтверждено"},
    )

    assert response.status_code == 404



def test_commercial_offer_verification_history_api_returns_latest_first(client, db):
    offer, _, _ = create_api_offer(db)

    first = SupplierOfferVerificationDB(
        offer_id=offer.id,
        verification_status="Подтверждено",
        verified_at=datetime(2026, 1, 1, 10, 0),
        verified_by="Первый проверяющий",
    )
    second = SupplierOfferVerificationDB(
        offer_id=offer.id,
        verification_status="Отклонено",
        verified_at=datetime(2026, 1, 2, 10, 0),
        verified_by="Второй проверяющий",
    )
    db.add_all([first, second])
    db.commit()

    response = client.get(
        f"/commercial/offers/{offer.id}/verifications"
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result) == 2
    assert result[0]["verification_status"] == "Отклонено"
    assert result[0]["verified_by"] == "Второй проверяющий"
    assert result[1]["verification_status"] == "Подтверждено"
    assert result[1]["verified_by"] == "Первый проверяющий"



def test_commercial_offer_verification_history_api_returns_empty_list(client, db):
    offer, _, _ = create_api_offer(db)

    response = client.get(
        f"/commercial/offers/{offer.id}/verifications"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_commercial_offer_verification_history_api_returns_404_for_missing_offer(client):
    response = client.get(
        "/commercial/offers/999999/verifications"
    )

    assert response.status_code == 404

def test_product_duplicates_api_finds_potential_name_matches(client, db):
    token = uuid.uuid4().hex

    manufacturer_a = ManufacturerDB(name=f"Производитель A {token}")
    manufacturer_b = ManufacturerDB(name=f"Производитель B {token}")
    db.add_all([manufacturer_a, manufacturer_b])
    db.flush()

    first = ProductDB(
        name=f"Кабель силовой медный 3х2.5 {token}",
        manufacturer_id=manufacturer_a.id,
        unit="м",
        category="Кабель",
    )
    second = ProductDB(
        name=f"Кабель силовой медный 3х2,5 {token}",
        manufacturer_id=manufacturer_a.id,
        unit="м",
        category="Провод",
    )
    similar_without_attributes = ProductDB(
        name=f"Кабель силовой медный 3х2.5 бухта {token}",
        manufacturer_id=manufacturer_a.id,
    )
    unrelated = ProductDB(
        name=f"Болт оцинкованный М8 {token}",
        manufacturer_id=manufacturer_a.id,
        unit="м",
        category="Кабель",
    )
    other_manufacturer = ProductDB(
        name=f"Кабель силовой медный 3х2,5 {token}",
        manufacturer_id=manufacturer_b.id,
        unit="м",
        category="Провод",
    )

    db.add_all([
        first,
        second,
        similar_without_attributes,
        unrelated,
        other_manufacturer,
    ])
    db.commit()

    response = client.get("/commercial/products/duplicates")

    assert response.status_code == 200

    potential_groups = [
        group
        for group in response.json()["groups"]
        if group["type"] == "potential_name_match"
        and token in group["match_value"]
    ]

    assert len(potential_groups) == 1

    group = potential_groups[0]
    assert group["manufacturer_id"] == manufacturer_a.id
    assert group["requires_review"] is True
    assert group["similarity_percent"] >= 85
    assert group["matching_attributes"] == ["unit"]
    assert {
        product["id"] for product in group["products"]
    } == {first.id, second.id}


def test_product_duplicate_review_api_create_list_and_update(client, db):
    token = uuid.uuid4().hex
    first = ProductDB(name=f"Товар первый {token}")
    second = ProductDB(name=f"Товар второй {token}")
    db.add_all([first, second])
    db.commit()
    db.refresh(first)
    db.refresh(second)

    response = client.post(
        "/commercial/products/duplicate-reviews",
        json={
            "product_id_1": second.id,
            "product_id_2": first.id,
            "comment": "Проверить характеристики",
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["product_id_1"] == min(first.id, second.id)
    assert created["product_id_2"] == max(first.id, second.id)
    assert created["status"] == "Ожидает решения"
    assert created["comment"] == "Проверить характеристики"
    assert created["reviewed_at"] is None

    duplicate = client.post(
        "/commercial/products/duplicate-reviews",
        json={
            "product_id_1": first.id,
            "product_id_2": second.id,
        },
    )
    assert duplicate.status_code == 409

    listing = client.get("/commercial/products/duplicate-reviews")
    assert listing.status_code == 200
    assert listing.json()["count"] >= 1
    assert any(item["id"] == created["id"] for item in listing.json()["reviews"])

    updated = client.put(
        f"/commercial/products/duplicate-reviews/{created['id']}",
        json={
            "status": "Один товар",
            "comment": "Это один и тот же товар",
        },
    )
    assert updated.status_code == 200
    result = updated.json()
    assert result["status"] == "Один товар"
    assert result["comment"] == "Это один и тот же товар"
    assert result["reviewed_at"] is not None

    db.refresh(
        db.query(ProductDuplicateReviewDB)
        .filter_by(id=created["id"])
        .one()
    )


def test_product_duplicate_review_api_validates_input(client, db):
    token = uuid.uuid4().hex
    product = ProductDB(name=f"Товар проверки {token}")
    db.add(product)
    db.commit()
    db.refresh(product)

    same_product = client.post(
        "/commercial/products/duplicate-reviews",
        json={
            "product_id_1": product.id,
            "product_id_2": product.id,
        },
    )
    assert same_product.status_code == 422

    missing_product = client.post(
        "/commercial/products/duplicate-reviews",
        json={
            "product_id_1": product.id,
            "product_id_2": 999999999,
        },
    )
    assert missing_product.status_code == 404

    invalid_id = client.post(
        "/commercial/products/duplicate-reviews",
        json={
            "product_id_1": True,
            "product_id_2": product.id,
        },
    )
    assert invalid_id.status_code == 422

    invalid_status = client.put(
        "/commercial/products/duplicate-reviews/999999999",
        json={"status": "Автоматически объединить"},
    )
    assert invalid_status.status_code == 422

    missing_review = client.put(
        "/commercial/products/duplicate-reviews/999999999",
        json={"status": "Один товар"},
    )
    assert missing_review.status_code == 404


def test_product_duplicate_review_api_lifecycle(client, db):
    token = uuid.uuid4().hex
    first = ProductDB(name=f"Товар A {token}")
    second = ProductDB(name=f"Товар B {token}")
    db.add_all([first, second])
    db.commit()
    db.refresh(first)
    db.refresh(second)

    created = client.post(
        "/commercial/products/duplicate-reviews",
        json={
            "product_id_1": first.id,
            "product_id_2": second.id,
            "comment": "Первичная проверка",
        },
    )
    assert created.status_code == 200
    review_id = created.json()["id"]
    assert created.json()["reviewed_at"] is None

    decided = client.put(
        f"/commercial/products/duplicate-reviews/{review_id}",
        json={"status": "Один товар", "comment": "Подтверждено"},
    )
    assert decided.status_code == 200
    assert decided.json()["reviewed_at"] is not None
    assert decided.json()["comment"] == "Подтверждено"

    changed = client.put(
        f"/commercial/products/duplicate-reviews/{review_id}",
        json={"status": "Разные товары"},
    )
    assert changed.status_code == 200
    assert changed.json()["reviewed_at"] is not None
    assert changed.json()["comment"] == "Подтверждено"

    reopened = client.put(
        f"/commercial/products/duplicate-reviews/{review_id}",
        json={"status": "Ожидает решения", "comment": None},
    )
    assert reopened.status_code == 200
    assert reopened.json()["reviewed_at"] is None
    assert reopened.json()["comment"] is None

    db.refresh(first)
    db.refresh(second)
    assert first.name == f"Товар A {token}"
    assert second.name == f"Товар B {token}"
