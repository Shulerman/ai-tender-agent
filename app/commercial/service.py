from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.database import TenderDB
from app.commercial.models import (
    ManufacturerDB,
    SupplierDB,
    ProductDB,
    SupplierOfferDB,
    PriceListImportDB,
    CommercialAnalysisDB,
    CommercialMatchDB,
)


def _validate_fields(data: dict, allowed_fields: set, required_fields: set):
    """Проверяет состав и обязательные поля входных данных."""

    if not isinstance(data, dict):
        raise ValueError("Данные должны быть переданы в виде словаря")

    unknown_fields = set(data.keys()) - allowed_fields

    if unknown_fields:
        raise ValueError(
            f"Неизвестные поля: {', '.join(sorted(unknown_fields))}"
        )

    missing_fields = {
        field
        for field in required_fields
        if data.get(field) is None or data.get(field) == ""
    }

    if missing_fields:
        raise ValueError(
            f"Не заполнены обязательные поля: "
            f"{', '.join(sorted(missing_fields))}"
        )


def _validate_non_negative(value, field_name: str):
    """Проверяет, что значение является неотрицательным числом."""

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Некорректное значение поля {field_name}")

    if not number.is_finite() or number < 0:
        raise ValueError(
            f"Поле {field_name} должно быть неотрицательным числом"
        )


def _save_record(db: Session, record, data: dict):
    """Сохраняет запись и возвращает обновлённый объект."""

    try:
        for field, value in data.items():
            setattr(record, field, value)

        db.add(record)
        db.commit()
        db.refresh(record)

        return record

    except Exception:
        db.rollback()
        raise


def upsert_manufacturer(db: Session, manufacturer_data: dict):
    """Создаёт производителя или обновляет существующего по названию."""

    allowed_fields = {
        "name",
        "country",
        "website",
        "description",
    }

    _validate_fields(
        manufacturer_data,
        allowed_fields,
        {"name"},
    )

    name = manufacturer_data["name"].strip()

    if not name:
        raise ValueError("Название производителя не может быть пустым")

    existing = db.query(ManufacturerDB).filter(
        ManufacturerDB.name == name
    ).first()

    data = dict(manufacturer_data)
    data["name"] = name

    if existing is not None:
        return _save_record(db, existing, data), "updated"

    manufacturer = ManufacturerDB()

    return _save_record(db, manufacturer, data), "created"


def upsert_supplier(db: Session, supplier_data: dict):
    """Создаёт поставщика или обновляет существующего."""

    allowed_fields = {
        "name",
        "inn",
        "country",
        "region",
        "address",
        "contact_person",
        "phone",
        "email",
        "website",
        "description",
    }

    _validate_fields(
        supplier_data,
        allowed_fields,
        {"name"},
    )

    name = supplier_data["name"].strip()

    if not name:
        raise ValueError("Название поставщика не может быть пустым")

    inn = supplier_data.get("inn")

    if isinstance(inn, str):
        inn = inn.strip() or None

    if inn:
        existing = db.query(SupplierDB).filter(
            SupplierDB.inn == inn
        ).first()
    else:
        existing = db.query(SupplierDB).filter(
            SupplierDB.name == name,
            SupplierDB.inn.is_(None),
        ).first()

    data = dict(supplier_data)
    data["name"] = name
    data["inn"] = inn

    if existing is not None:
        return _save_record(db, existing, data), "updated"

    supplier = SupplierDB()

    return _save_record(db, supplier, data), "created"


def upsert_product(db: Session, product_data: dict):
    """Создаёт товар или обновляет его по артикулу либо названию."""

    allowed_fields = {
        "name",
        "article_number",
        "manufacturer_id",
        "description",
        "technical_characteristics",
        "unit",
        "category",
    }

    _validate_fields(
        product_data,
        allowed_fields,
        {"name"},
    )

    name = product_data["name"].strip()

    if not name:
        raise ValueError("Название товара не может быть пустым")

    article_number = product_data.get("article_number")
    manufacturer_id = product_data.get("manufacturer_id")

    if article_number:
        query = db.query(ProductDB).filter(
            ProductDB.article_number == article_number,
        )
    else:
        query = db.query(ProductDB).filter(
            ProductDB.name == name,
        )

    if manufacturer_id is None:
        query = query.filter(ProductDB.manufacturer_id.is_(None))
    else:
        manufacturer = db.get(ManufacturerDB, manufacturer_id)

        if manufacturer is None:
            raise ValueError("Производитель не найден")

        query = query.filter(
            ProductDB.manufacturer_id == manufacturer_id
        )

    existing = query.first()

    data = dict(product_data)
    data["name"] = name

    if existing is not None:
        return _save_record(db, existing, data), "updated"

    product = ProductDB()

    return _save_record(db, product, data), "created"


def create_price_list_import(db: Session, import_data: dict):
    """Создаёт запись об импорте прайс-листа поставщика."""

    allowed_fields = {
        "supplier_id",
        "file_name",
        "file_path",
        "file_hash",
        "sheet_name",
        "header_row",
        "column_mapping",
    }

    _validate_fields(
        import_data,
        allowed_fields,
        {"supplier_id", "file_name"},
    )

    supplier = db.get(SupplierDB, import_data["supplier_id"])

    if supplier is None:
        raise ValueError("Поставщик не найден")

    file_name = import_data["file_name"]

    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("Имя файла не должно быть пустым")

    header_row = import_data.get("header_row", 1)

    if (
        not isinstance(header_row, int)
        or isinstance(header_row, bool)
        or header_row < 1
    ):
        raise ValueError("header_row должен быть положительным целым числом")

    file_hash = import_data.get("file_hash")

    if file_hash is not None:
        if (
            not isinstance(file_hash, str)
            or len(file_hash) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in file_hash)
        ):
            raise ValueError("file_hash должен содержать 64 шестнадцатеричных символа")

        file_hash = file_hash.lower()

    column_mapping = import_data.get("column_mapping")

    if column_mapping is not None and not isinstance(column_mapping, dict):
        raise ValueError("column_mapping должен быть словарём")

    file_path = import_data.get("file_path")
    sheet_name = import_data.get("sheet_name")

    if file_path is not None and not isinstance(file_path, str):
        raise ValueError("file_path должен быть строкой")

    if sheet_name is not None and not isinstance(sheet_name, str):
        raise ValueError("sheet_name должен быть строкой")

    record = PriceListImportDB(
        supplier_id=import_data["supplier_id"],
        file_name=file_name.strip(),
        file_path=file_path,
        file_hash=file_hash,
        sheet_name=sheet_name,
        header_row=header_row,
        column_mapping=column_mapping,
        status="Создан",
        total_rows=0,
        imported_rows=0,
        error_rows=0,
        errors=None,
        created_at=datetime.now(),
    )

    try:
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    except Exception:
        db.rollback()
        raise


def create_supplier_offer(db: Session, offer_data: dict):
    """Создаёт новое предложение поставщика без перезаписи истории цен."""

    allowed_fields = {
        "supplier_id",
        "product_id",
        "price",
        "currency",
        "available_quantity",
        "availability_status",
        "delivery_time_days",
        "payment_terms",
        "delivery_cost",
        "received_at",
        "valid_until",
        "source_type",
        "source_reference",
        "verification_status",
        "notes",
    }

    _validate_fields(
        offer_data,
        allowed_fields,
        {
            "supplier_id",
            "product_id",
            "price",
            "received_at",
            "source_type",
        },
    )

    _validate_non_negative(offer_data["price"], "price")

    if offer_data.get("delivery_cost") is not None:
        _validate_non_negative(
            offer_data["delivery_cost"],
            "delivery_cost",
        )

    if offer_data.get("available_quantity") is not None:
        _validate_non_negative(
            offer_data["available_quantity"],
            "available_quantity",
        )

    supplier = db.get(SupplierDB, offer_data["supplier_id"])
    product = db.get(ProductDB, offer_data["product_id"])

    if supplier is None:
        raise ValueError("Поставщик не найден")

    if product is None:
        raise ValueError("Товар не найден")

    if not isinstance(offer_data["received_at"], datetime):
        raise ValueError("received_at должен иметь тип datetime")

    if (
        offer_data.get("valid_until") is not None
        and not isinstance(offer_data["valid_until"], datetime)
    ):
        raise ValueError("valid_until должен иметь тип datetime")

    if offer_data.get("delivery_time_days") is not None:
        days = offer_data["delivery_time_days"]

        if not isinstance(days, int) or isinstance(days, bool) or days < 0:
            raise ValueError(
                "delivery_time_days должно быть неотрицательным целым числом"
            )

    offer = SupplierOfferDB(**offer_data)

    try:
        db.add(offer)
        db.commit()
        db.refresh(offer)

        return offer

    except Exception:
        db.rollback()
        raise


def get_current_supplier_offers(
    db: Session,
    supplier_id: int = None,
    product_id: int = None,
):
    """Возвращает предложения, срок действия которых не истёк."""

    now = datetime.now()

    query = db.query(SupplierOfferDB).filter(
        (SupplierOfferDB.valid_until.is_(None))
        | (SupplierOfferDB.valid_until >= now)
    )

    if supplier_id is not None:
        query = query.filter(
            SupplierOfferDB.supplier_id == supplier_id
        )

    if product_id is not None:
        query = query.filter(
            SupplierOfferDB.product_id == product_id
        )

    return query.order_by(
        SupplierOfferDB.received_at.desc()
    ).all()


def create_commercial_analysis(db: Session, analysis_data: dict):
    """Создаёт коммерческий анализ существующего тендера."""

    allowed_fields = {
        "tender_id",
        "status",
        "total_purchase_cost",
        "additional_costs",
        "contract_revenue",
        "gross_profit",
        "gross_margin_percent",
        "currency",
        "data_completeness",
        "commercial_risks",
        "recommendations",
        "created_at",
        "completed_at",
    }

    _validate_fields(
        analysis_data,
        allowed_fields,
        {"tender_id"},
    )

    tender_id = analysis_data["tender_id"]

    tender = db.query(TenderDB).filter(
        TenderDB.tender_id == tender_id
    ).first()

    if tender is None:
        raise ValueError("Тендер не найден")

    for field in (
        "total_purchase_cost",
        "additional_costs",
        "contract_revenue",
    ):
        value = analysis_data.get(field)

        if value is not None:
            _validate_non_negative(value, field)

    data = dict(analysis_data)
    data.setdefault("created_at", datetime.now())

    analysis = CommercialAnalysisDB(**data)

    try:
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        return analysis

    except Exception:
        db.rollback()
        raise


def create_commercial_match(db: Session, match_data: dict):
    """Сохраняет сопоставление требования тендера с товаром."""

    allowed_fields = {
        "analysis_id",
        "product_id",
        "offer_id",
        "tender_requirement",
        "match_status",
        "match_score",
        "confirmed_characteristics",
        "missing_characteristics",
        "discrepancies",
        "evidence_status",
        "evidence_references",
        "estimated_quantity",
        "estimated_unit_price",
        "estimated_total_price",
        "currency",
        "notes",
        "recommendation",
        "created_at",
    }

    _validate_fields(
        match_data,
        allowed_fields,
        {"analysis_id", "tender_requirement"},
    )

    analysis = db.get(
        CommercialAnalysisDB,
        match_data["analysis_id"],
    )

    if analysis is None:
        raise ValueError("Коммерческий анализ не найден")

    product_id = match_data.get("product_id")
    offer_id = match_data.get("offer_id")

    product = None
    offer = None

    if product_id is not None:
        product = db.get(ProductDB, product_id)

        if product is None:
            raise ValueError("Товар не найден")

    if offer_id is not None:
        offer = db.get(SupplierOfferDB, offer_id)

        if offer is None:
            raise ValueError("Предложение поставщика не найдено")

        if product_id is not None and offer.product_id != product_id:
            raise ValueError(
                "Предложение поставщика относится к другому товару"
            )

        if product_id is None:
            product_id = offer.product_id

    score = match_data.get("match_score")

    if score is not None:
        try:
            score = Decimal(str(score))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Некорректное значение match_score")

        if not score.is_finite() or score < 0 or score > 100:
            raise ValueError("match_score должен быть от 0 до 100")

    for field in (
        "estimated_quantity",
        "estimated_unit_price",
        "estimated_total_price",
    ):
        value = match_data.get(field)

        if value is not None:
            _validate_non_negative(value, field)

    data = dict(match_data)
    data["product_id"] = product_id
    data["match_score"] = score
    data.setdefault("created_at", datetime.now())

    match = CommercialMatchDB(**data)

    try:
        db.add(match)
        db.commit()
        db.refresh(match)

        return match

    except Exception:
        db.rollback()
        raise


def get_commercial_matches(db: Session, analysis_id: int):
    """Возвращает все сопоставления для конкретного анализа."""

    analysis = db.get(CommercialAnalysisDB, analysis_id)

    if analysis is None:
        raise ValueError("Коммерческий анализ не найден")

    return (
        db.query(CommercialMatchDB)
        .filter(CommercialMatchDB.analysis_id == analysis_id)
        .order_by(CommercialMatchDB.id.asc())
        .all()
    )
