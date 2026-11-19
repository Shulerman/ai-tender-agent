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
    SupplierProductMappingDB,
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
    assert offer.unit == "упаковка"
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
    assert offers[0].unit == "шт."
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


def test_manual_match_creates_supplier_product_mapping(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Товар для постоянного сопоставления {test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            ["  ABC-001  ", "Товар поставщика", 500, "RUB", "шт."],
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

    mapping = (
        db.query(SupplierProductMappingDB)
        .filter_by(
            supplier_id=supplier.id,
            normalized_supplier_article_number="abc-001",
        )
        .one()
    )

    assert mapping.supplier_article_number == "ABC-001"
    assert mapping.product_id == product.id
    assert mapping.supplier_product_name == "Товар поставщика"


def test_manual_match_rejects_supplier_article_remapping(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product_a = create_product(
        db,
        test_id,
        f"Первый товар {test_id}",
    )
    product_b = create_product(
        db,
        test_id,
        f"Второй товар {test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            ["CONFLICT-001", "Товар поставщика", 500, "RUB", "шт."],
            ["CONFLICT-001", "Товар поставщика", 550, "RUB", "шт."],
        ],
    )
    result = run_import(db, supplier, file_path)

    rows = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=result["import_id"])
        .order_by(PriceListImportRowDB.source_row)
        .all()
    )

    assert len(rows) == 2

    match_import_row(
        db,
        import_id=result["import_id"],
        row_id=rows[0].id,
        product_id=product_a.id,
    )

    with pytest.raises(ValueError, match="уже связан с другим"):
        match_import_row(
            db,
            import_id=result["import_id"],
            row_id=rows[1].id,
            product_id=product_b.id,
        )

    mapping = (
        db.query(SupplierProductMappingDB)
        .filter_by(
            supplier_id=supplier.id,
            normalized_supplier_article_number="conflict-001",
        )
        .one()
    )

    db.refresh(rows[1])

    assert mapping.product_id == product_a.id
    assert rows[1].status == "Требует сопоставления"
    assert rows[1].product_id is None

    assert db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"],
    ).count() == 1


def test_reimport_uses_supplier_product_mapping(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Товар из каталога {test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            ["ABC-002", "Первоначальное название поставщика", 500, "RUB", "шт."],
        ],
    )

    first_result = run_import(db, supplier, file_path)

    first_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=first_result["import_id"])
        .one()
    )

    assert first_row.status == "Требует сопоставления"

    match_import_row(
        db,
        import_id=first_result["import_id"],
        row_id=first_row.id,
        product_id=product.id,
    )

    first_offer = (
        db.query(SupplierOfferDB)
        .filter_by(import_id=first_result["import_id"])
        .one()
    )

    assert first_offer.price == 500

    second_file = create_excel_file(
        tmp_path,
        [
            ["abc-002", "Изменённое название поставщика", 650, "RUB", "шт."],
        ],
    )

    second_result = run_import(db, supplier, second_file)

    second_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=second_result["import_id"])
        .one()
    )

    assert second_row.status == "Сопоставлен"
    assert second_row.product_id == product.id

    offers = (
        db.query(SupplierOfferDB)
        .filter_by(supplier_id=supplier.id)
        .order_by(SupplierOfferDB.id)
        .all()
    )

    assert len(offers) == 2
    assert offers[0].price == 500
    assert offers[1].price == 650
    assert offers[0].import_id != offers[1].import_id


def test_manual_match_without_article_does_not_create_mapping(
    db,
    test_id,
    tmp_path,
):
    supplier = create_supplier(db, test_id)
    product = create_product(
        db,
        test_id,
        f"Товар без артикула поставщика {test_id}",
    )

    file_path = create_excel_file(
        tmp_path,
        [
            [None, "Товар без артикула", 700, "RUB", "шт."],
        ],
    )

    result = run_import(db, supplier, file_path)

    import_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=result["import_id"])
        .one()
    )

    assert import_row.status == "Требует сопоставления"

    match_import_row(
        db,
        import_id=result["import_id"],
        row_id=import_row.id,
        product_id=product.id,
    )

    db.refresh(import_row)

    assert import_row.status == "Сопоставлен"
    assert import_row.product_id == product.id

    assert db.query(SupplierProductMappingDB).filter_by(
        supplier_id=supplier.id,
    ).count() == 0

    assert db.query(SupplierOfferDB).filter_by(
        import_id=result["import_id"],
        product_id=product.id,
    ).count() == 1


def test_supplier_product_mapping_is_isolated_between_suppliers(
    db,
    test_id,
    tmp_path,
):
    supplier_one = create_supplier(db, f"{test_id}-one")
    supplier_two = create_supplier(db, f"{test_id}-two")

    product_one = create_product(
        db,
        test_id,
        f"Товар первого поставщика {test_id}",
    )

    first_dir = tmp_path / "first"
    first_dir.mkdir()

    first_file = create_excel_file(
        first_dir,
        [
            ["ABC-100", "Товар первого поставщика", 500, "RUB", "шт."],
        ],
    )

    first_result = run_import(db, supplier_one, first_file)

    first_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=first_result["import_id"])
        .one()
    )

    assert first_row.status == "Требует сопоставления"

    match_import_row(
        db,
        import_id=first_result["import_id"],
        row_id=first_row.id,
        product_id=product_one.id,
    )

    second_dir = tmp_path / "second"
    second_dir.mkdir()

    second_file = create_excel_file(
        second_dir,
        [
            ["ABC-100", "Совершенно другой товар", 900, "RUB", "шт."],
        ],
    )

    second_result = run_import(db, supplier_two, second_file)

    second_row = (
        db.query(PriceListImportRowDB)
        .filter_by(import_id=second_result["import_id"])
        .one()
    )

    assert second_row.status == "Требует сопоставления"
    assert second_row.product_id is None

    mapping_one = (
        db.query(SupplierProductMappingDB)
        .filter_by(
            supplier_id=supplier_one.id,
            normalized_supplier_article_number="abc-100",
        )
        .one()
    )

    assert mapping_one.product_id == product_one.id

    assert db.query(SupplierProductMappingDB).filter_by(
        supplier_id=supplier_two.id,
        normalized_supplier_article_number="abc-100",
    ).count() == 0

    assert db.query(SupplierOfferDB).filter_by(
        import_id=second_result["import_id"],
    ).count() == 0
