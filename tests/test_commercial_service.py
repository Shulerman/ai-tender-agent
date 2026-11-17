from datetime import datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, TenderDB
from app.commercial.models import PriceListImportRowDB
from app.commercial.service import (
    upsert_manufacturer,
    upsert_supplier,
    upsert_product,
    create_price_list_import,
    create_supplier_offer,
    get_current_supplier_offers,
    create_commercial_analysis,
    create_commercial_match,
    get_commercial_matches,
)


@pytest.fixture
def test_id():
    return uuid.uuid4().hex


@pytest.fixture
def db():
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


def create_test_tender(db, tender_id="TEST-COMMERCIAL-001"):
    """Создаёт тестовый тендер, если он ещё не существует."""

    tender = db.query(TenderDB).filter(
        TenderDB.tender_id == tender_id
    ).first()

    if tender is None:
        tender = TenderDB(
            tender_id=tender_id,
            title="Тестовый тендер для коммерческого анализа",
        )
        db.add(tender)
        db.commit()
        db.refresh(tender)

    return tender


def create_test_analysis(db):
    """Создаёт тестовый коммерческий анализ."""

    tender = create_test_tender(db)

    return create_commercial_analysis(
        db,
        {"tender_id": tender.tender_id},
    )


def create_test_import(db, test_id):
    """Создаёт тестовый импорт прайс-листа."""

    supplier, _ = upsert_supplier(
        db,
        {"name": f"Поставщик прайс-листа-{test_id}"},
    )

    return create_price_list_import(
        db,
        {
            "supplier_id": supplier.id,
            "file_name": f"price_list_{test_id}.xlsx",
            "sheet_name": "Товары",
            "header_row": 1,
        },
    )


def test_create_manufacturer(db, test_id):
    manufacturer, status = upsert_manufacturer(
        db,
        {"name": f"Тестовый производитель-{test_id}"},
    )

    assert status == "created"
    assert manufacturer.id is not None


def test_create_supplier(db, test_id):
    supplier, status = upsert_supplier(
        db,
        {"name": f"Тестовый поставщик-{test_id}"},
    )

    assert status == "created"
    assert supplier.id is not None


def test_create_product(db, test_id):
    manufacturer, _ = upsert_manufacturer(
        db,
        {"name": f"Производитель товара-{test_id}"},
    )

    product, status = upsert_product(
        db,
        {
            "name": f"Тестовый товар-{test_id}",
            "manufacturer_id": manufacturer.id,
            "unit": "шт.",
        },
    )

    assert status == "created"
    assert product.id is not None


def test_create_price_list_import_row_without_product(db, test_id):
    """Неизвестный товар сохраняется без автоматического создания продукта."""

    price_import = create_test_import(db, test_id)

    row = PriceListImportRowDB(
        import_id=price_import.id,
        source_row=2,
        source_values={"A": "Новый товар", "B": "1500.00"},
        source_name="Новый товар",
        source_article_number="NEW-001",
        price=Decimal("1500.00"),
        currency="RUB",
        unit="шт.",
        status="Требует сопоставления",
        created_at=datetime.now(),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    assert row.id is not None
    assert row.import_id == price_import.id
    assert row.product_id is None
    assert row.status == "Требует сопоставления"

    product = db.query(
        PriceListImportRowDB
    ).filter(
        PriceListImportRowDB.id == row.id
    ).first()

    assert product.product_id is None


def test_create_price_list_import_row_with_existing_product(db, test_id):
    """Строка импорта может ссылаться на существующий товар."""

    price_import = create_test_import(db, test_id)

    product, _ = upsert_product(
        db,
        {"name": f"Существующий товар-{test_id}"},
    )

    row = PriceListImportRowDB(
        import_id=price_import.id,
        source_row=3,
        source_name=product.name,
        source_article_number="EXISTING-001",
        price=Decimal("2500.00"),
        currency="RUB",
        product_id=product.id,
        status="Импортировано",
        created_at=datetime.now(),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    assert row.id is not None
    assert row.product_id == product.id
    assert row.import_id == price_import.id


def test_duplicate_source_row_is_rejected_within_same_import(db, test_id):
    """Одна исходная строка не может дважды попасть в один импорт."""

    price_import = create_test_import(db, test_id)

    first_row = PriceListImportRowDB(
        import_id=price_import.id,
        source_row=5,
        source_name="Первый товар",
        price=Decimal("100.00"),
        created_at=datetime.now(),
    )

    db.add(first_row)
    db.commit()

    duplicate_row = PriceListImportRowDB(
        import_id=price_import.id,
        source_row=5,
        source_name="Дублирующая строка",
        price=Decimal("200.00"),
        created_at=datetime.now(),
    )

    db.add(duplicate_row)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

    rows = db.query(PriceListImportRowDB).filter(
        PriceListImportRowDB.import_id == price_import.id,
        PriceListImportRowDB.source_row == 5,
    ).all()

    assert len(rows) == 1
    assert rows[0].source_name == "Первый товар"


def test_same_source_row_number_is_allowed_in_another_import(db, test_id):
    """Одинаковые номера строк допустимы в разных импортах."""

    first_import = create_test_import(db, f"{test_id}-first")
    second_import = create_test_import(db, f"{test_id}-second")

    first_row = PriceListImportRowDB(
        import_id=first_import.id,
        source_row=2,
        source_name="Товар первого импорта",
        price=Decimal("100.00"),
        created_at=datetime.now(),
    )

    second_row = PriceListImportRowDB(
        import_id=second_import.id,
        source_row=2,
        source_name="Товар второго импорта",
        price=Decimal("200.00"),
        created_at=datetime.now(),
    )

    db.add_all([first_row, second_row])
    db.commit()

    assert first_row.id is not None
    assert second_row.id is not None
    assert first_row.import_id != second_row.import_id
    assert first_row.source_row == second_row.source_row


def test_create_supplier_offer(db):
    supplier, _ = upsert_supplier(
        db,
        {"name": "Поставщик предложения"},
    )

    product, _ = upsert_product(
        db,
        {"name": "Товар предложения"},
    )

    offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier.id,
            "product_id": product.id,
            "price": Decimal("1500.00"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    assert offer.id is not None
    assert offer.price == Decimal("1500.00")


def test_current_supplier_offers_exclude_expired(db):
    supplier, _ = upsert_supplier(
        db,
        {"name": "Поставщик срока действия"},
    )

    product, _ = upsert_product(
        db,
        {"name": "Товар срока действия"},
    )

    current_offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier.id,
            "product_id": product.id,
            "price": Decimal("1000.00"),
            "received_at": datetime.now(),
            "valid_until": datetime.now() + timedelta(days=7),
            "source_type": "manual",
        },
    )

    expired_offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier.id,
            "product_id": product.id,
            "price": Decimal("900.00"),
            "received_at": datetime.now() - timedelta(days=30),
            "valid_until": datetime.now() - timedelta(days=1),
            "source_type": "manual",
        },
    )

    offers = get_current_supplier_offers(
        db,
        supplier_id=supplier.id,
        product_id=product.id,
    )

    offer_ids = {offer.id for offer in offers}

    assert current_offer.id in offer_ids
    assert expired_offer.id not in offer_ids


def test_negative_supplier_offer_price_is_rejected(db):
    supplier, _ = upsert_supplier(
        db,
        {"name": "Поставщик отрицательной цены"},
    )

    product, _ = upsert_product(
        db,
        {"name": "Товар отрицательной цены"},
    )

    with pytest.raises(ValueError):
        create_supplier_offer(
            db,
            {
                "supplier_id": supplier.id,
                "product_id": product.id,
                "price": Decimal("-100.00"),
                "received_at": datetime.now(),
                "source_type": "manual",
            },
        )


def test_create_commercial_analysis(db):
    analysis = create_test_analysis(db)

    assert analysis.id is not None
    assert analysis.tender_id == "TEST-COMMERCIAL-001"
    assert analysis.status == "Не завершён"


def test_analysis_for_missing_tender_is_rejected(db):
    with pytest.raises(ValueError, match="Тендер не найден"):
        create_commercial_analysis(
            db,
            {"tender_id": "NONEXISTENT-TENDER"},
        )


def test_create_commercial_match(db):
    analysis = create_test_analysis(db)

    product, _ = upsert_product(
        db,
        {"name": "Товар для сопоставления"},
    )

    match = create_commercial_match(
        db,
        {
            "analysis_id": analysis.id,
            "product_id": product.id,
            "tender_requirement": "Поставка 100 единиц товара",
            "match_status": "Частичное соответствие",
            "match_score": Decimal("85.00"),
            "evidence_status": "Не проверено",
        },
    )

    assert match.id is not None
    assert match.analysis_id == analysis.id
    assert match.product_id == product.id
    assert match.match_score == Decimal("85.00")


def test_match_rejects_offer_for_another_product(db):
    analysis = create_test_analysis(db)

    supplier, _ = upsert_supplier(
        db,
        {"name": "Поставщик для проверки связи"},
    )

    product_one, _ = upsert_product(
        db,
        {"name": "Первый товар для проверки"},
    )

    product_two, _ = upsert_product(
        db,
        {"name": "Второй товар для проверки"},
    )

    offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier.id,
            "product_id": product_one.id,
            "price": Decimal("1000.00"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    with pytest.raises(
        ValueError,
        match="относится к другому товару",
    ):
        create_commercial_match(
            db,
            {
                "analysis_id": analysis.id,
                "product_id": product_two.id,
                "offer_id": offer.id,
                "tender_requirement": "Поставка товара",
            },
        )


def test_match_score_must_be_between_zero_and_hundred(db):
    analysis = create_test_analysis(db)

    with pytest.raises(ValueError, match="от 0 до 100"):
        create_commercial_match(
            db,
            {
                "analysis_id": analysis.id,
                "tender_requirement": "Техническое требование",
                "match_score": Decimal("105.00"),
            },
        )


def test_get_commercial_matches(db):
    analysis = create_test_analysis(db)

    product, _ = upsert_product(
        db,
        {"name": "Товар для получения сопоставлений"},
    )

    create_commercial_match(
        db,
        {
            "analysis_id": analysis.id,
            "product_id": product.id,
            "tender_requirement": "Требование номер один",
        },
    )

    matches = get_commercial_matches(db, analysis.id)

    assert len(matches) == 1
    assert matches[0].tender_requirement == "Требование номер один"
    assert matches[0].analysis_id == analysis.id
