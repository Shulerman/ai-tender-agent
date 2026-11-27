from datetime import datetime, timedelta
from decimal import Decimal
import json
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, TenderDB
from app.documents.models import (
    TenderDocumentDB,
    TenderAnalysisDB,
    TenderRequirementDB,
)
from app.commercial.models import (
    PriceListImportRowDB,
    SupplierOfferVerificationDB,
    ProductUnitConversionDB,
    CommercialMatchRunDB,
    CommercialMatchDB,
)
from app.commercial.unit_normalizer import normalize_unit_price
from app.commercial.service import (
    run_commercial_matcher,
    upsert_manufacturer,
    upsert_supplier,
    upsert_product,
    create_price_list_import,
    create_supplier_offer,
    verify_supplier_offer,
    get_current_supplier_offers,
    create_commercial_analysis,
    create_commercial_match,
    get_commercial_matches,
    upsert_product_unit_conversion,
    get_product_unit_conversion,
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


def create_test_requirement(
    db,
    tender,
    quantity="Не указано",
    unit="шт.",
):
    """Создаёт документ, анализ и требование для тестового тендера."""

    document = TenderDocumentDB(
        document_uuid=str(uuid.uuid4()),
        tender_id=tender.id,
        original_name="matcher_test.html",
        file_path="matcher_test.html",
        file_hash=None,
        detected_extension=".html",
        size_bytes=100,
    )
    db.add(document)
    db.flush()

    tender_analysis = TenderAnalysisDB(
        document_id=document.id,
        analysis_type="technical_requirements",
        status="Завершён",
        result_json={},
    )
    db.add(tender_analysis)
    db.flush()

    requirement_attributes = {
        "name": "Тестовый товар",
        "quantity": quantity,
        "unit": unit,
        "attributes": [
            {
                "name": "diameter",
                "value": 10,
                "unit": "mm",
                "operator": "=",
                "is_required": True,
                "evidence": [
                    {
                        "claim": "Диаметр должен быть 10 мм",
                        "quote": "Диаметр изделия должен составлять 10 мм",
                    }
                ],
            },
            {
                "name": "material",
                "value": "steel",
                "unit": None,
                "operator": "=",
                "is_required": True,
                "evidence": [],
            },
        ],
        "evidence": [
            {
                "claim": "Требуется товар с диаметром 10 мм",
                "quote": "Диаметр изделия должен составлять 10 мм",
            }
        ],
    }

    requirement = TenderRequirementDB(
        document_id=document.id,
        analysis_id=tender_analysis.id,
        requirement_type="product",
        requirement_text="Тестовое требование к товару",
        attributes=requirement_attributes,
        evidence_quote="Диаметр изделия должен составлять 10 мм",
        extraction_status="Проверено",
    )
    db.add(requirement)
    db.commit()

    db.refresh(document)
    db.refresh(tender_analysis)
    db.refresh(requirement)

    return document, tender_analysis, requirement


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


def test_create_product_unit_conversion(db, test_id):
    """Создаёт общий коэффициент пересчёта единиц товара."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Бумага-{test_id}",
            "unit": "шт.",
        },
    )

    conversion, status = upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("500"),
        },
    )

    assert status == "created"
    assert conversion.id is not None
    assert conversion.supplier_id is None
    assert conversion.conversion_factor == Decimal("500")


def test_update_product_unit_conversion(db, test_id):
    """Повторное сохранение обновляет коэффициент, а не создаёт дубль."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Бумага для обновления-{test_id}",
            "unit": "шт.",
        },
    )

    conversion_data = {
        "product_id": product.id,
        "source_unit": "упаковка",
        "target_unit": "шт.",
        "conversion_factor": Decimal("500"),
    }

    first, first_status = upsert_product_unit_conversion(
        db,
        conversion_data,
    )

    updated, update_status = upsert_product_unit_conversion(
        db,
        {
            **conversion_data,
            "conversion_factor": Decimal("400"),
        },
    )

    assert first_status == "created"
    assert update_status == "updated"
    assert updated.id == first.id
    assert updated.conversion_factor == Decimal("400")

    count = db.query(ProductUnitConversionDB).filter(
        ProductUnitConversionDB.product_id == product.id,
    ).count()

    assert count == 1


def test_supplier_conversion_has_priority_over_global(db, test_id):
    """Коэффициент поставщика имеет приоритет над общим коэффициентом."""

    supplier, _ = upsert_supplier(
        db,
        {"name": f"Поставщик бумаги-{test_id}"},
    )

    product, _ = upsert_product(
        db,
        {
            "name": f"Бумага с разными упаковками-{test_id}",
            "unit": "шт.",
        },
    )

    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("500"),
        },
    )

    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "supplier_id": supplier.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("250"),
        },
    )

    supplier_conversion = get_product_unit_conversion(
        db,
        product.id,
        "упаковка",
        "шт.",
        supplier.id,
    )

    global_conversion = get_product_unit_conversion(
        db,
        product.id,
        "упаковка",
        "шт.",
    )

    assert supplier_conversion.conversion_factor == Decimal("250")
    assert global_conversion.conversion_factor == Decimal("500")


def test_supplier_conversion_falls_back_to_global(db, test_id):
    """Если правила поставщика нет, используется общее правило."""

    supplier, _ = upsert_supplier(
        db,
        {"name": f"Поставщик без своего правила-{test_id}"},
    )

    product, _ = upsert_product(
        db,
        {
            "name": f"Бумага с общим правилом-{test_id}",
            "unit": "шт.",
        },
    )

    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("500"),
        },
    )

    conversion = get_product_unit_conversion(
        db,
        product.id,
        "упаковка",
        "шт.",
        supplier.id,
    )

    assert conversion is not None
    assert conversion.supplier_id is None
    assert conversion.conversion_factor == Decimal("500")


def test_product_unit_conversion_rejects_non_positive_factor(db, test_id):
    """Нулевой и отрицательный коэффициенты запрещены."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Бумага с неверным коэффициентом-{test_id}",
            "unit": "шт.",
        },
    )

    for factor in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError):
            upsert_product_unit_conversion(
                db,
                {
                    "product_id": product.id,
                    "source_unit": "упаковка",
                    "target_unit": "шт.",
                    "conversion_factor": factor,
                },
            )


def test_product_unit_conversion_rejects_wrong_target_unit(db, test_id):
    """Целевая единица должна совпадать с единицей товара в каталоге."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Бумага с неверной целевой единицей-{test_id}",
            "unit": "шт.",
        },
    )

    with pytest.raises(ValueError, match="Целевая единица"):
        upsert_product_unit_conversion(
            db,
            {
                "product_id": product.id,
                "source_unit": "упаковка",
                "target_unit": "кг",
                "conversion_factor": Decimal("500"),
            },
        )


def test_product_unit_conversion_rejects_missing_product(db):
    """Нельзя создать коэффициент для несуществующего товара."""

    with pytest.raises(ValueError, match="Товар не найден"):
        upsert_product_unit_conversion(
            db,
            {
                "product_id": 999999999,
                "source_unit": "упаковка",
                "target_unit": "шт.",
                "conversion_factor": Decimal("500"),
            },
        )


def test_product_unit_conversion_rejects_missing_supplier(db, test_id):
    """Нельзя создать индивидуальный коэффициент для неизвестного поставщика."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар без поставщика-{test_id}",
            "unit": "шт.",
        },
    )

    with pytest.raises(ValueError, match="Поставщик не найден"):
        upsert_product_unit_conversion(
            db,
            {
                "product_id": product.id,
                "supplier_id": 999999999,
                "source_unit": "упаковка",
                "target_unit": "шт.",
                "conversion_factor": Decimal("500"),
            },
        )


def test_product_unit_conversion_rejects_stale_target_unit(db, test_id):
    """Старый коэффициент нельзя получить после изменения единицы товара."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар с изменённой единицей-{test_id}",
            "unit": "шт.",
        },
    )

    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("500"),
        },
    )

    upsert_product(
        db,
        {
            "name": product.name,
            "unit": "кг",
        },
    )

    with pytest.raises(ValueError, match="Целевая единица"):
        get_product_unit_conversion(
            db,
            product.id,
            "упаковка",
            "шт.",
        )


@pytest.mark.parametrize(
    "price, source_unit, target_unit, expected",
    [
        ("10", "г", "кг", "10000"),
        ("2", "мл", "л", "2000"),
        ("5", "см", "м", "500"),
        ("3", "см²", "м²", "30000"),
        ("12", "штук", "шт.", "12"),
        ("100", "кг", "г", "0.1"),
    ],
)
def test_normalize_standard_unit_price(
    price,
    source_unit,
    target_unit,
    expected,
):
    result = normalize_unit_price(
        price,
        source_unit,
        target_unit,
    )

    assert result == Decimal(expected)


def test_normalize_unit_price_rejects_different_families():
    with pytest.raises(ValueError, match="разных физических категорий"):
        normalize_unit_price(
            "100",
            "кг",
            "л",
        )


def test_normalize_unit_price_rejects_negative_price():
    with pytest.raises(ValueError, match="неотрицательным"):
        normalize_unit_price(
            "-10",
            "кг",
            "кг",
        )


def test_normalize_unknown_unit_requires_conversion_rule():
    with pytest.raises(ValueError, match="требуется товар и база данных"):
        normalize_unit_price(
            "500",
            "упаковка",
            "шт.",
        )


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
    assert offer.verification_status == "Не проверено"


def test_supplier_offer_verification_status_cannot_be_set_on_creation(db):
    supplier, _ = upsert_supplier(
        db,
        {"name": "Поставщик с запрещённым статусом"},
    )

    product, _ = upsert_product(
        db,
        {"name": "Товар с запрещённым статусом"},
    )

    with pytest.raises(ValueError, match="verification_status"):
        create_supplier_offer(
            db,
            {
                "supplier_id": supplier.id,
                "product_id": product.id,
                "price": Decimal("1500.00"),
                "received_at": datetime.now(),
                "source_type": "manual",
                "verification_status": "Подтверждено",
            },
        )



def test_verify_supplier_offer_updates_status_and_creates_history(db):
    supplier, _ = upsert_supplier(db, {"name": "Поставщик проверки"})
    product, _ = upsert_product(db, {"name": "Товар проверки"})
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

    verification = verify_supplier_offer(
        db,
        offer.id,
        "Подтверждено",
        verified_by="Проверяющий",
        notes="Цена подтверждена",
    )

    db.refresh(offer)
    history = db.query(SupplierOfferVerificationDB).filter_by(
        offer_id=offer.id
    ).all()

    assert offer.verification_status == "Подтверждено"
    assert verification.verification_status == "Подтверждено"
    assert verification.verified_by == "Проверяющий"
    assert verification.notes == "Цена подтверждена"
    assert len(history) == 1


def test_verify_supplier_offer_repeated_decisions_preserve_history(db):
    supplier, _ = upsert_supplier(db, {"name": "Поставщик повторной проверки"})
    product, _ = upsert_product(db, {"name": "Товар повторной проверки"})
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

    verify_supplier_offer(db, offer.id, "Отклонено")
    verify_supplier_offer(db, offer.id, "Подтверждено")

    db.refresh(offer)
    history = (
        db.query(SupplierOfferVerificationDB)
        .filter_by(offer_id=offer.id)
        .order_by(SupplierOfferVerificationDB.id.asc())
        .all()
    )

    assert offer.verification_status == "Подтверждено"
    assert [item.verification_status for item in history] == [
        "Отклонено",
        "Подтверждено",
    ]


def test_verify_supplier_offer_rejects_unknown_offer(db):
    with pytest.raises(ValueError, match="не найдено"):
        verify_supplier_offer(db, 999999999, "Подтверждено")


def test_verify_supplier_offer_rejects_invalid_status(db):
    supplier, _ = upsert_supplier(db, {"name": "Поставщик неверного статуса"})
    product, _ = upsert_product(db, {"name": "Товар неверного статуса"})
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

    with pytest.raises(ValueError, match="verification_status"):
        verify_supplier_offer(db, offer.id, "Не проверено")

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


def test_get_all_supplier_offers_includes_expired(db):
    from app.commercial.service import get_all_supplier_offers

    supplier, _ = upsert_supplier(
        db,
        {"name": "Поставщик всех предложений"},
    )
    product, _ = upsert_product(
        db,
        {"name": "Товар всех предложений"},
    )

    expired_offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier.id,
            "product_id": product.id,
            "price": Decimal("900"),
            "received_at": datetime.now() - timedelta(days=30),
            "valid_until": datetime.now() - timedelta(days=1),
            "source_type": "manual",
        },
    )

    offers = get_all_supplier_offers(
        db,
        supplier_id=supplier.id,
        product_id=product.id,
    )

    assert expired_offer.id in {offer.id for offer in offers}

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


def test_upsert_product_persists_technical_attributes(db, test_id):
    attributes = {
        "diameter": {"value": 10, "unit": "mm"},
        "material": {"value": "steel"},
    }

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар с техническими атрибутами-{test_id}",
            "technical_attributes": attributes,
        },
    )

    assert product.technical_attributes == attributes


def test_create_commercial_match_with_requirement_and_run(db):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()

    _, tender_analysis, requirement = create_test_requirement(db, tender)

    match_run = CommercialMatchRunDB(
        commercial_analysis_id=analysis.id,
        tender_analysis_id=tender_analysis.id,
    )
    db.add(match_run)
    db.commit()
    db.refresh(match_run)

    match = create_commercial_match(
        db,
        {
            "analysis_id": analysis.id,
            "tender_requirement_id": requirement.id,
            "match_run_id": match_run.id,
            "tender_requirement": "Ошибочный текст из входных данных",
        },
    )

    assert match.tender_requirement_id == requirement.id
    assert match.tender_requirement == requirement.requirement_text
    assert match.match_run_id == match_run.id
    assert match.analysis_id == analysis.id


def test_match_rejects_requirement_from_another_tender(db):
    analysis = create_test_analysis(db)
    other_tender = create_test_tender(
        db,
        f"TEST-COMMERCIAL-OTHER-{uuid.uuid4().hex}",
    )
    _, _, requirement = create_test_requirement(db, other_tender)

    with pytest.raises(ValueError, match="относится к другому тендеру"):
        create_commercial_match(
            db,
            {
                "analysis_id": analysis.id,
                "tender_requirement_id": requirement.id,
                "tender_requirement": requirement.requirement_text,
            },
        )


def test_match_rejects_run_from_another_commercial_analysis(db):
    analysis = create_test_analysis(db)
    other_tender = create_test_tender(
        db,
        f"TEST-COMMERCIAL-OTHER-{uuid.uuid4().hex}",
    )
    other_analysis = create_commercial_analysis(
        db,
        {"tender_id": other_tender.tender_id},
    )
    _, tender_analysis, _ = create_test_requirement(db, other_tender)

    match_run = CommercialMatchRunDB(
        commercial_analysis_id=other_analysis.id,
        tender_analysis_id=tender_analysis.id,
    )
    db.add(match_run)
    db.commit()
    db.refresh(match_run)

    with pytest.raises(
        ValueError,
        match="относится к другому коммерческому анализу",
    ):
        create_commercial_match(
            db,
            {
                "analysis_id": analysis.id,
                "match_run_id": match_run.id,
                "tender_requirement": "Проверка чужого запуска",
            },
        )


def test_match_rejects_run_with_different_tender_analysis(db):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()

    document, tender_analysis, requirement = create_test_requirement(
        db,
        tender,
    )

    other_tender_analysis = TenderAnalysisDB(
        document_id=document.id,
        analysis_type="technical_requirements",
        status="Завершён",
        result_json={},
    )
    db.add(other_tender_analysis)
    db.commit()
    db.refresh(other_tender_analysis)

    match_run = CommercialMatchRunDB(
        commercial_analysis_id=analysis.id,
        tender_analysis_id=other_tender_analysis.id,
    )
    db.add(match_run)
    db.commit()
    db.refresh(match_run)

    with pytest.raises(
        ValueError,
        match="не относится к анализу этого запуска",
    ):
        create_commercial_match(
            db,
            {
                "analysis_id": analysis.id,
                "tender_requirement_id": requirement.id,
                "match_run_id": match_run.id,
                "tender_requirement": requirement.requirement_text,
            },
        )


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

@pytest.mark.parametrize(
    "global_factor, supplier_factor, expected_price",
    [
        (Decimal("500"), None, Decimal("2")),
        (Decimal("500"), Decimal("250"), Decimal("4")),
        (Decimal("500"), Decimal("1000"), Decimal("1")),
    ],
)
def test_normalize_packaging_price_with_database_conversion(
    db,
    test_id,
    global_factor,
    supplier_factor,
    expected_price,
):
    """Цена упаковки пересчитывается по правилу поставщика или общему правилу."""

    supplier, _ = upsert_supplier(
        db,
        {"name": f"Поставщик нормализации-{test_id}"},
    )

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар нормализации-{test_id}",
            "unit": "шт.",
        },
    )

    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": global_factor,
        },
    )

    if supplier_factor is not None:
        upsert_product_unit_conversion(
            db,
            {
                "product_id": product.id,
                "supplier_id": supplier.id,
                "source_unit": "упаковка",
                "target_unit": "шт.",
                "conversion_factor": supplier_factor,
            },
        )

    result = normalize_unit_price(
        price="1000",
        source_unit="упаковка",
        target_unit="шт.",
        db=db,
        product_id=product.id,
        supplier_id=supplier.id,
    )

    assert result == expected_price


def test_normalize_unknown_unit_rejects_missing_database_conversion(
    db,
    test_id,
):
    """Без сохранённого коэффициента упаковка не пересчитывается."""

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар без коэффициента-{test_id}",
            "unit": "шт.",
        },
    )

    with pytest.raises(ValueError, match="Не найден коэффициент пересчёта"):
        normalize_unit_price(
            price="1000",
            source_unit="упаковка",
            target_unit="шт.",
            db=db,
            product_id=product.id,
        )

def test_compare_supplier_offers_ranks_by_total_cost(db, test_id):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db,
        {"name": f"Товар сравнения-{test_id}", "unit": "шт."},
    )
    supplier_one, _ = upsert_supplier(
        db, {"name": f"Поставщик дорогой-{test_id}"}
    )
    supplier_two, _ = upsert_supplier(
        db, {"name": f"Поставщик выгодный-{test_id}"}
    )

    expensive = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_one.id,
            "product_id": product.id,
            "price": Decimal("100"),
            "unit": "шт.",
            "available_quantity": Decimal("20"),
            "delivery_cost": Decimal("500"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )
    cheaper = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_two.id,
            "product_id": product.id,
            "price": Decimal("110"),
            "unit": "шт.",
            "available_quantity": Decimal("20"),
            "delivery_cost": Decimal("0"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    result = compare_supplier_offers(
        db,
        product.id,
        Decimal("10"),
    )

    ranked_ids = [
        item["offer"].id
        for item in result["ranked_offers"]
    ]

    assert ranked_ids == [cheaper.id, expensive.id]
    assert result["ranked_offers"][0]["goods_total"] == Decimal("1100")
    assert result["ranked_offers"][0]["landed_total"] == Decimal("1100")
    assert result["ranked_offers"][1]["landed_total"] == Decimal("1500")


def test_compare_supplier_offers_excludes_non_rub_currency(db, test_id):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db, {"name": f"Товар валютной проверки-{test_id}", "unit": "шт."}
    )
    supplier_rub, _ = upsert_supplier(
        db, {"name": f"Поставщик RUB-{test_id}"}
    )
    supplier_usd, _ = upsert_supplier(
        db, {"name": f"Поставщик USD-{test_id}"}
    )

    rub_offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_rub.id,
            "product_id": product.id,
            "price": Decimal("100"),
            "currency": "RUB",
            "unit": "шт.",
            "available_quantity": Decimal("20"),
            "delivery_cost": Decimal("0"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )
    usd_offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_usd.id,
            "product_id": product.id,
            "price": Decimal("25"),
            "currency": "USD",
            "unit": "шт.",
            "available_quantity": Decimal("20"),
            "delivery_cost": Decimal("0"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    result = compare_supplier_offers(db, product.id, Decimal("10"))

    assert [item["offer"].id for item in result["ranked_offers"]] == [rub_offer.id]
    assert result["expired_offers"] == []
    assert len(result["unranked_offers"]) == 1
    excluded = result["unranked_offers"][0]
    assert excluded["offer"].id == usd_offer.id
    assert excluded["offer"].price == Decimal("25")
    assert excluded["offer"].currency == "USD"
    assert "RUB" in excluded["reason"]

def test_compare_supplier_offers_does_not_rank_unknown_delivery_or_quantity(
    db,
    test_id,
):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db,
        {"name": f"Товар неполных данных-{test_id}", "unit": "шт."},
    )
    supplier_one, _ = upsert_supplier(
        db, {"name": f"Поставщик без доставки-{test_id}"}
    )
    supplier_two, _ = upsert_supplier(
        db, {"name": f"Поставщик без количества-{test_id}"}
    )

    no_delivery = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_one.id,
            "product_id": product.id,
            "price": Decimal("10"),
            "unit": "шт.",
            "available_quantity": Decimal("20"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )
    no_quantity = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_two.id,
            "product_id": product.id,
            "price": Decimal("5"),
            "unit": "шт.",
            "delivery_cost": Decimal("0"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    result = compare_supplier_offers(
        db,
        product.id,
        Decimal("10"),
    )

    ranked_ids = [
        item["offer"].id
        for item in result["ranked_offers"]
    ]
    unranked_ids = {
        item["offer"].id
        for item in result["unranked_offers"]
    }

    assert ranked_ids == []
    assert unranked_ids == {no_delivery.id, no_quantity.id}


def test_compare_supplier_offers_normalizes_kg_to_g(db, test_id):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db,
        {"name": f"Товар пересчёта кг-г-{test_id}", "unit": "г"},
    )
    supplier, _ = upsert_supplier(
        db,
        {"name": f"Поставщик кг-г-{test_id}"},
    )

    offer = create_supplier_offer(
        db,
        {
            "supplier_id": supplier.id,
            "product_id": product.id,
            "price": Decimal("1200"),
            "unit": "кг",
            "available_quantity": Decimal("5"),
            "delivery_cost": Decimal("100"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    result = compare_supplier_offers(
        db,
        product.id,
        Decimal("2000"),
    )

    assert len(result["ranked_offers"]) == 1
    ranked = result["ranked_offers"][0]

    assert ranked["offer"].id == offer.id
    assert ranked["normalized_unit_price"] == Decimal("1.200")
    assert ranked["available_quantity"] == Decimal("5000")
    assert ranked["goods_total"] == Decimal("2400.000")
    assert ranked["landed_total"] == Decimal("2500.000")
    assert result["unranked_offers"] == []


def test_compare_supplier_offers_uses_supplier_packaging_override(db, test_id):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db,
        {"name": f"Товар упаковочного пересчёта-{test_id}", "unit": "шт."},
    )
    supplier_global, _ = upsert_supplier(
        db,
        {"name": f"Поставщик общей упаковки-{test_id}"},
    )
    supplier_override, _ = upsert_supplier(
        db,
        {"name": f"Поставщик индивидуальной упаковки-{test_id}"},
    )

    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("10"),
        },
    )
    upsert_product_unit_conversion(
        db,
        {
            "product_id": product.id,
            "supplier_id": supplier_override.id,
            "source_unit": "упаковка",
            "target_unit": "шт.",
            "conversion_factor": Decimal("20"),
        },
    )

    offer_global = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_global.id,
            "product_id": product.id,
            "price": Decimal("100"),
            "unit": "упаковка",
            "available_quantity": Decimal("100"),
            "delivery_cost": Decimal("0"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )
    offer_override = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_override.id,
            "product_id": product.id,
            "price": Decimal("100"),
            "unit": "упаковка",
            "available_quantity": Decimal("50"),
            "delivery_cost": Decimal("0"),
            "received_at": datetime.now(),
            "source_type": "manual",
        },
    )

    result = compare_supplier_offers(
        db,
        product.id,
        Decimal("1000"),
    )

    ranked = result["ranked_offers"]

    assert len(ranked) == 2
    assert ranked[0]["offer"].id == offer_override.id
    assert ranked[1]["offer"].id == offer_global.id

    assert ranked[0]["normalized_unit_price"] == Decimal("5.000")
    assert ranked[0]["available_quantity"] == Decimal("1000")
    assert ranked[0]["landed_total"] == Decimal("5000.000")

    assert ranked[1]["normalized_unit_price"] == Decimal("10.000")
    assert ranked[1]["available_quantity"] == Decimal("1000")
    assert ranked[1]["landed_total"] == Decimal("10000.000")

    assert result["unranked_offers"] == []


def test_compare_supplier_offers_keeps_expired_offers_separate(db, test_id):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db,
        {"name": f"Товар просроченных предложений-{test_id}", "unit": "шт."},
    )
    supplier_ranked, _ = upsert_supplier(
        db, {"name": f"Поставщик просроченный с ценой-{test_id}"}
    )
    supplier_unranked, _ = upsert_supplier(
        db, {"name": f"Поставщик просроченный без доставки-{test_id}"}
    )

    expired_ranked = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_ranked.id,
            "product_id": product.id,
            "price": Decimal("25"),
            "unit": "шт.",
            "available_quantity": Decimal("100"),
            "delivery_cost": Decimal("50"),
            "received_at": datetime.now() - timedelta(days=10),
            "valid_until": datetime.now() - timedelta(days=1),
            "source_type": "manual",
        },
    )
    expired_unranked = create_supplier_offer(
        db,
        {
            "supplier_id": supplier_unranked.id,
            "product_id": product.id,
            "price": Decimal("20"),
            "unit": "шт.",
            "available_quantity": Decimal("100"),
            "received_at": datetime.now() - timedelta(days=10),
            "valid_until": datetime.now() - timedelta(days=1),
            "source_type": "manual",
        },
    )

    result = compare_supplier_offers(db, product.id, Decimal("10"))

    assert result["ranked_offers"] == []
    assert result["unranked_offers"] == []

    assert len(result["expired_offers"]) == 1
    ranked = result["expired_offers"][0]
    assert ranked["offer"].id == expired_ranked.id
    assert ranked["landed_total"] == Decimal("300")
    assert ranked["freshness_status"] == "Требуется перепроверка"
    assert ranked["freshness_warning"] == (
        "Требуется уточнить у поставщика актуальность цены и наличия"
    )

    assert len(result["expired_unranked_offers"]) == 1
    unranked = result["expired_unranked_offers"][0]
    assert unranked["offer"].id == expired_unranked.id
    assert unranked["reason"] == "Стоимость доставки не указана"
    assert unranked["freshness_status"] == "Требуется перепроверка"
    assert unranked["freshness_warning"] == (
        "Требуется уточнить у поставщика актуальность цены и наличия"
    )

def test_compare_supplier_offers_excludes_rejected_and_insufficient_quantity(
    db,
    test_id,
):
    from app.commercial.service import compare_supplier_offers

    product, _ = upsert_product(
        db,
        {"name": f"Товар проверки доступности-{test_id}", "unit": "шт."},
    )
    suppliers = []
    for suffix in ("достаточно", "мало", "отклонён"):
        supplier, _ = upsert_supplier(
            db,
            {"name": f"Поставщик {suffix}-{test_id}"},
        )
        suppliers.append(supplier)

    def make_offer(supplier, quantity):
        return create_supplier_offer(
            db,
            {
                "supplier_id": supplier.id,
                "product_id": product.id,
                "price": Decimal("10"),
                "unit": "шт.",
                "available_quantity": Decimal(quantity),
                "delivery_cost": Decimal("0"),
                "received_at": datetime.now(),
                "source_type": "manual",
            },
        )

    sufficient_offer = make_offer(suppliers[0], "100")
    insufficient_offer = make_offer(suppliers[1], "5")
    rejected_offer = make_offer(suppliers[2], "100")
    verify_supplier_offer(db, rejected_offer.id, "Отклонено")

    result = compare_supplier_offers(
        db,
        product.id,
        Decimal("10"),
    )

    ranked = result["ranked_offers"]
    assert len(ranked) == 1
    assert ranked[0]["offer"].id == sufficient_offer.id
    assert ranked[0]["verification_status"] == "Не проверено"
    assert len(result["unranked_offers"]) == 1
    unranked = result["unranked_offers"][0]
    assert unranked["offer"].id == insufficient_offer.id
    assert unranked["reason"] == "Недостаточно товара у поставщика"


def test_run_commercial_matcher_counts_invalid_requirement_attributes(
    db,
    test_id,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, requirement = create_test_requirement(db, tender)

    requirement.attributes = None

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар для некорректного требования-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
                "material": "steel",
            },
        },
    )
    db.commit()

    catalog_size = db.query(type(product)).count()

    run = run_commercial_matcher(
        db,
        analysis.id,
        tender_analysis.id,
    )

    matches = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        tender_requirement_id=requirement.id,
    ).all()

    assert run.status == "Завершён"
    assert run.statistics["requirements_total"] == 1
    assert run.statistics["products_checked"] == catalog_size
    assert run.statistics["insufficient_data"] == catalog_size
    assert run.statistics["matches_created"] == 0
    assert matches == []


@pytest.mark.parametrize(
    ("quantity", "expected_quantity", "expected_status"),
    [
        ("100", Decimal("100"), "parsed"),
        ("по заявкам", None, "missing"),
        ("от 100 до 200", None, "ambiguous"),
    ],
)
def test_run_commercial_matcher_parses_requirement_quantity(
    db,
    test_id,
    quantity,
    expected_quantity,
    expected_status,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, requirement = create_test_requirement(
        db,
        tender,
        quantity=quantity,
        unit="шт.",
    )

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар для проверки количества-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
                "material": "steel",
            },
        },
    )

    run = run_commercial_matcher(
        db,
        analysis.id,
        tender_analysis.id,
    )

    match = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        product_id=product.id,
    ).one()

    evidence = json.loads(match.evidence_references)
    quantity_analysis = evidence["quantity_analysis"]

    assert match.estimated_quantity == expected_quantity
    assert quantity_analysis["source_quantity"] == quantity
    assert quantity_analysis["source_unit"] == "шт."
    assert quantity_analysis["parse_status"] == expected_status
    assert quantity_analysis["parse_reason"]


def test_run_commercial_matcher_preserves_original_error(
    db,
    test_id,
    monkeypatch,
):
    import importlib

    commercial_service = importlib.import_module("app.commercial.service")

    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, _ = create_test_requirement(db, tender)

    upsert_product(
        db,
        {
            "name": f"Товар для проверки ошибки-{test_id}",
            "technical_attributes": {"diameter": {"value": 10, "unit": "mm"}},
        },
    )
    db.commit()

    original_error = RuntimeError("matcher processing failed")

    def fail_comparison(*args, **kwargs):
        raise original_error

    monkeypatch.setattr(
        commercial_service,
        "compare_product_to_requirement",
        fail_comparison,
    )

    with pytest.raises(RuntimeError, match="matcher processing failed") as exc:
        run_commercial_matcher(db, analysis.id, tender_analysis.id)

    assert exc.value is original_error

    failed_run = db.query(CommercialMatchRunDB).filter_by(
        commercial_analysis_id=analysis.id,
        status="Ошибка",
    ).order_by(CommercialMatchRunDB.id.desc()).first()

    assert failed_run is not None
    assert failed_run.error == "matcher processing failed"
    assert failed_run.completed_at is not None


def test_run_commercial_matcher_preserves_original_error_if_failure_log_fails(
    db,
    test_id,
    monkeypatch,
):
    import importlib

    commercial_service = importlib.import_module("app.commercial.service")

    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, _ = create_test_requirement(db, tender)

    upsert_product(
        db,
        {
            "name": f"Товар для проверки сбоя журнала-{test_id}",
            "technical_attributes": {"diameter": {"value": 10, "unit": "mm"}},
        },
    )
    db.commit()

    original_error = RuntimeError("matcher processing failed")
    persistence_error = RuntimeError("failure log commit failed")

    def fail_comparison(*args, **kwargs):
        raise original_error

    def fail_commit():
        raise persistence_error

    monkeypatch.setattr(
        commercial_service,
        "compare_product_to_requirement",
        fail_comparison,
    )
    monkeypatch.setattr(db, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="matcher processing failed") as exc:
        run_commercial_matcher(db, analysis.id, tender_analysis.id)

    assert exc.value is original_error

    if hasattr(original_error, "__notes__"):
        assert any(
            "failure log commit failed" in note
            for note in original_error.__notes__
        )

    db.rollback()

    assert db.query(CommercialMatchRunDB).filter_by(
        commercial_analysis_id=analysis.id,
        status="Ошибка",
    ).count() == 0


def test_run_commercial_matcher_creates_full_match_and_preserves_evidence(
    db,
    test_id,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, requirement = create_test_requirement(db, tender)

    product, _ = upsert_product(
        db,
        {
            "name": f"Полностью подходящий товар-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
                "material": "steel",
            },
        },
    )

    run = run_commercial_matcher(
        db,
        analysis.id,
        tender_analysis.id,
    )

    match = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        product_id=product.id,
    ).one()

    evidence = json.loads(match.evidence_references)

    assert match.evidence_status == "Не проверено"
    assert evidence["extraction_status"] == requirement.extraction_status
    assert run.status == "Завершён"
    assert run.statistics["requirements_total"] == 1
    # Matcher проверяет весь каталог, а не только товар этого теста.
    assert run.statistics["products_checked"] >= 1
    assert run.statistics["matches_created"] >= 1
    assert run.statistics["full_matches"] >= 1
    assert match.tender_requirement_id == requirement.id
    assert match.match_status == "Полное соответствие"
    assert evidence["requirement_attribute_evidence"]["diameter"][0][
        "quote"
    ] == "Диаметр изделия должен составлять 10 мм"
    assert "не являются доказательствами характеристик" in evidence[
        "evidence_note"
    ]


def test_run_commercial_matcher_converts_standard_units_in_service(
    db,
    test_id,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, requirement = create_test_requirement(db, tender)

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар с эквивалентной единицей-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 1, "unit": "cm"},
                "material": "steel",
            },
        },
    )

    run = run_commercial_matcher(
        db,
        analysis.id,
        tender_analysis.id,
    )

    match = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        product_id=product.id,
        tender_requirement_id=requirement.id,
    ).one()

    confirmed = json.loads(match.confirmed_characteristics)

    assert run.status == "Завершён"
    assert run.algorithm_version == "1.1"
    assert match.match_status == "Полное соответствие"
    assert len(confirmed) == 2


def test_run_commercial_matcher_separates_potential_analogues(
    db,
    test_id,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, _ = create_test_requirement(db, tender)

    full_product, _ = upsert_product(
        db,
        {
            "name": f"Полное соответствие-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
                "material": "steel",
            },
        },
    )
    analogue_product, _ = upsert_product(
        db,
        {
            "name": f"Потенциальный аналог-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
            },
        },
    )

    run = run_commercial_matcher(
        db,
        analysis.id,
        tender_analysis.id,
    )

    matches = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id
    ).all()
    statuses = {
        match.product_id: match.match_status
        for match in matches
    }

    assert statuses[full_product.id] == "Полное соответствие"
    assert statuses[analogue_product.id] == "Потенциальный аналог"
    # В общей статистике могут учитываться товары из других тестов.
    assert run.statistics["full_matches"] >= 1
    assert run.statistics["potential_analogues"] >= 1
    assert run.statistics["matches_created"] >= 2


def test_run_commercial_matcher_does_not_create_match_without_confirmed_data(
    db,
    test_id,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, _ = create_test_requirement(db, tender)

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар без подтверждённых данных-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 12, "unit": "cm"},
            },
        },
    )

    run = run_commercial_matcher(
        db,
        analysis.id,
        tender_analysis.id,
    )

    matches = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        product_id=product.id,
    ).all()

    assert matches == []
    assert run.status == "Завершён"
    # Проверяем отсутствие совпадения для конкретного товара выше.
    # Остальные товары каталога могут иметь собственные совпадения.
    assert run.statistics["products_checked"] >= 1
    assert run.statistics["insufficient_data"] >= 1


def test_run_commercial_matcher_saves_parsed_quantity(db, test_id):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, requirement = create_test_requirement(db, tender)

    requirement_attributes = dict(requirement.attributes)
    requirement_attributes.update({"quantity": 25, "unit": "шт"})
    requirement.attributes = requirement_attributes

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар с распознанным количеством-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
                "material": "steel",
            },
        },
    )
    db.commit()

    run = run_commercial_matcher(db, analysis.id, tender_analysis.id)
    match = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        product_id=product.id,
    ).one()

    evidence = json.loads(match.evidence_references)
    assert match.estimated_quantity == Decimal("25")
    assert evidence["quantity_analysis"]["parse_status"] == "parsed"
    assert evidence["quantity_analysis"]["source_quantity"] == "25"
    assert evidence["quantity_analysis"]["source_unit"] == "шт"


def test_run_commercial_matcher_does_not_estimate_ambiguous_quantity(
    db,
    test_id,
):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, tender_analysis, requirement = create_test_requirement(db, tender)

    requirement_attributes = dict(requirement.attributes)
    requirement_attributes.update({
        "quantity": "от 10 до 20",
        "unit": "шт",
    })
    requirement.attributes = requirement_attributes

    product, _ = upsert_product(
        db,
        {
            "name": f"Товар с диапазоном количества-{test_id}",
            "technical_attributes": {
                "diameter": {"value": 10, "unit": "mm"},
                "material": "steel",
            },
        },
    )
    db.commit()

    run = run_commercial_matcher(db, analysis.id, tender_analysis.id)
    match = db.query(CommercialMatchDB).filter_by(
        match_run_id=run.id,
        product_id=product.id,
    ).one()

    evidence = json.loads(match.evidence_references)
    assert match.estimated_quantity is None
    assert evidence["quantity_analysis"]["parse_status"] == "ambiguous"
    assert evidence["quantity_analysis"]["source_quantity"] == "от 10 до 20"



def test_manual_commercial_match_rejects_technical_requirement(db):
    analysis = create_test_analysis(db)
    tender = db.query(TenderDB).filter_by(
        tender_id=analysis.tender_id
    ).one()
    _, _, requirement = create_test_requirement(db, tender)
    requirement.requirement_type = "technical"
    db.commit()

    with pytest.raises(
        ValueError,
        match="только товарные требования",
    ):
        create_commercial_match(
            db,
            {
                "analysis_id": analysis.id,
                "tender_requirement_id": requirement.id,
                "tender_requirement": requirement.requirement_text,
            },
        )
