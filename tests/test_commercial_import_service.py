from datetime import datetime
from decimal import Decimal
import uuid

import pytest
from openpyxl import Workbook

from app.database import SessionLocal
from app.commercial.models import (
    ProductDB,
    PriceListImportDB,
    PriceListImportRowDB,
    SupplierDB,
    SupplierOfferDB,
)
from app.commercial.import_service import import_price_list, match_import_row


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_id():
    return uuid.uuid4().hex


def create_supplier(db, test_id):
    supplier = SupplierDB(
        name=f"Тестовый поставщик импорта-{test_id}"
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def create_product(db, test_id, name, article_number=None):
    product = ProductDB(
        name=name,
        article_number=article_number,
        created_at=datetime.now(),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def create_excel_file(tmp_path, rows):
    file_path = tmp_path / "supplier_prices.xlsx"

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

    for row in rows:
        worksheet.append(row)

    workbook.save(file_path)
    workbook.close()

    return file_path


COLUMN_MAPPING = {
    "article_number": 1,
    "name": 2,
    "price": 3,
    "currency": 4,
    "unit": 5,
}


def run_import(db, supplier, file_path):
    return import_price_list(
        db,
        supplier_id=supplier.id,
        file_path=str(file_path),
        column_mapping=COLUMN_MAPPING,
    )


def test_import_matches_product_by_article(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Бумага офисная {test_id}",
        f"A-100-{test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            [f"A-100-{test_id}", "Бумага офисная", 350.50, "RUB", "упаковка"],
        ],
    )

    result = run_import(db, supplier, file_path)

    row = db.query(PriceListImportRowDB).filter_by(
        import_id=result["import_id"]
    ).one()

    offer = db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"]
    ).one()

    assert row.product_id == product.id
    assert row.status == "Сопоставлен"
    assert offer.product_id == product.id
    assert offer.verification_status == "Не проверено"
    assert offer.source_reference is not None
    assert result["matched_offers"] == 1
    assert result["unmatched_rows"] == 0


def test_import_falls_back_to_exact_name(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Бумага офисная {test_id}",
        f"A-100-{test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            [
                "UNKNOWN-999",
                f"  БУМАГА   офисная {test_id}  ",
                350.50,
                "RUB",
                "упаковка",
            ],
        ],
    )

    result = run_import(db, supplier, file_path)

    row = db.query(PriceListImportRowDB).filter_by(
        import_id=result["import_id"]
    ).one()

    offer = db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"]
    ).one()

    assert row.product_id == product.id
    assert row.status == "Сопоставлен"
    assert offer.product_id == product.id


def test_unknown_product_is_not_created(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)

    file_path = create_excel_file(
        tmp_path,
        [
            [
                "NEW-001",
                "Новый неизвестный товар",
                1500,
                "RUB",
                "шт.",
            ],
        ],
    )

    products_before = db.query(ProductDB).count()

    result = run_import(db, supplier, file_path)

    products_after = db.query(ProductDB).count()

    row = db.query(PriceListImportRowDB).filter_by(
        import_id=result["import_id"]
    ).one()

    offers = db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"]
    ).all()

    assert products_after == products_before
    assert row.product_id is None
    assert row.status == "Требует сопоставления"
    assert offers == []
    assert result["unmatched_rows"] == 1


def test_ambiguous_article_requires_manual_matching(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)

    create_product(
        db,
        test_id,
        "Первый товар",
        "DUP-001",
    )
    create_product(
        db,
        test_id,
        "Второй товар",
        "DUP-001",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            [
                "DUP-001",
                "Первый товар",
                500,
                "RUB",
                "шт.",
            ],
        ],
    )

    result = run_import(db, supplier, file_path)

    row = db.query(PriceListImportRowDB).filter_by(
        import_id=result["import_id"]
    ).one()

    offers = db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"]
    ).all()

    assert row.product_id is None
    assert row.status == "Требует сопоставления"
    assert offers == []


def test_invalid_excel_row_is_saved(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)

    file_path = create_excel_file(
        tmp_path,
        [
            [
                "BAD-001",
                "Товар с некорректной ценой",
                "неизвестно",
                "RUB",
                "шт.",
            ],
        ],
    )

    result = run_import(db, supplier, file_path)

    row = db.query(PriceListImportRowDB).filter_by(
        import_id=result["import_id"]
    ).one()

    assert result["error_rows"] == 1
    assert result["imported_rows"] == 0
    assert row.status == "Ошибка"
    assert row.error is not None
    assert row.source_values is not None
    assert row.source_article_number == "BAD-001"


def test_import_rolls_back_on_commit_error(
    db,
    test_id,
    tmp_path,
    monkeypatch,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        "Тестовый товар",
        "ROLLBACK-001",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            [
                "ROLLBACK-001",
                "Тестовый товар",
                100,
                "RUB",
                "шт.",
            ],
        ],
    )

    def fail_commit():
        raise RuntimeError("Имитированная ошибка commit")

    monkeypatch.setattr(db, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="Имитированная ошибка"):
        run_import(db, supplier, file_path)

    assert db.query(PriceListImportDB).filter_by(
        supplier_id=supplier.id,
        file_name="supplier_prices.xlsx",
    ).count() == 0

    assert db.query(SupplierOfferDB).filter_by(
        product_id=product.id,
        supplier_id=supplier.id,
    ).count() == 0
def test_manual_match_creates_supplier_offer(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Товар для ручного сопоставления {test_id}",
        f"MANUAL-{test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            ["UNKNOWN-001", "Новый товар из прайса", 725.50, "RUB", "шт."],
        ],
    )
    result = run_import(db, supplier, file_path)

    import_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=result["import_id"])
        .one()
    )
    assert import_row.status == "Требует сопоставления"

    match_result = match_import_row(
        db,
        import_id=result["import_id"],
        row_id=import_row.id,
        product_id=product.id,
    )

    db.refresh(import_row)
    offers = (
        db.query(SupplierOfferDB)
        .filter_by(
            import_id=result["import_id"],
            supplier_id=supplier.id,
            product_id=product.id,
        )
        .all()
    )

    assert match_result["status"] == "Сопоставлен"
    assert match_result["product_id"] == product.id
    assert import_row.product_id == product.id
    assert import_row.status == "Сопоставлен"
    assert len(offers) == 1
    assert offers[0].price == Decimal("725.50")
    assert offers[0].currency == "RUB"
    assert offers[0].verification_status == "Не проверено"


def test_manual_match_rejects_unknown_product(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    file_path = create_excel_file(
        tmp_path,
        [
            ["UNKNOWN-002", "Товар без сопоставления", 100, "RUB", "шт."],
        ],
    )
    result = run_import(db, supplier, file_path)

    import_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=result["import_id"])
        .one()
    )

    with pytest.raises(ValueError, match="Товар каталога не найден"):
        match_import_row(
            db,
            import_id=result["import_id"],
            row_id=import_row.id,
            product_id=-999999,
        )

    db.refresh(import_row)
    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None
    assert db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"],
    ).count() == 0


def test_manual_match_rejects_already_matched_row(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Товар для повторного сопоставления {test_id}",
    )
    file_path = create_excel_file(
        tmp_path,
        [
            ["UNKNOWN-003", "Повторное сопоставление", 250, "RUB", "шт."],
        ],
    )
    result = run_import(db, supplier, file_path)

    import_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=result["import_id"])
        .one()
    )

    match_import_row(
        db,
        import_id=result["import_id"],
        row_id=import_row.id,
        product_id=product.id,
    )

    with pytest.raises(ValueError, match="уже обработана"):
        match_import_row(
            db,
            import_id=result["import_id"],
            row_id=import_row.id,
            product_id=product.id,
        )

    assert db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"],
        product_id=product.id,
    ).count() == 1


def test_manual_match_rejects_row_without_price(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Товар для строки без цены {test_id}",
    )
    file_path = create_excel_file(
        tmp_path,
        [
            ["UNKNOWN-004", "Товар без цены", 100, "RUB", "шт."],
        ],
    )
    result = run_import(db, supplier, file_path)

    import_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=result["import_id"])
        .one()
    )

    import_row.price = None
    db.commit()

    with pytest.raises(ValueError, match="отсутствует цена"):
        match_import_row(
            db,
            import_id=result["import_id"],
            row_id=import_row.id,
            product_id=product.id,
        )

    db.refresh(import_row)
    assert import_row.status == "Требует сопоставления"
    assert import_row.product_id is None
    assert db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"],
    ).count() == 0