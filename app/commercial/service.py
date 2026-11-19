from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.database import TenderDB
from app.commercial.unit_normalizer import get_unit_definition, normalize_unit_price
from app.commercial.models import (
    ManufacturerDB,
    SupplierDB,
    ProductDB,
    SupplierOfferDB,
    SupplierOfferVerificationDB,
    PriceListImportDB,
    CommercialAnalysisDB,
    CommercialMatchDB,
    ProductUnitConversionDB,
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


def upsert_product_unit_conversion(
    db: Session,
    conversion_data: dict,
):
    """Создаёт или обновляет коэффициент пересчёта единиц товара."""

    allowed_fields = {
        "product_id",
        "supplier_id",
        "source_unit",
        "target_unit",
        "conversion_factor",
    }

    _validate_fields(
        conversion_data,
        allowed_fields,
        {
            "product_id",
            "source_unit",
            "target_unit",
            "conversion_factor",
        },
    )

    product = db.get(ProductDB, conversion_data["product_id"])

    if product is None:
        raise ValueError("Товар не найден")

    supplier_id = conversion_data.get("supplier_id")

    if supplier_id is not None and db.get(SupplierDB, supplier_id) is None:
        raise ValueError("Поставщик не найден")

    source_unit = conversion_data["source_unit"].strip()
    target_unit = conversion_data["target_unit"].strip()

    if not source_unit or not target_unit:
        raise ValueError("Единицы измерения не могут быть пустыми")

    if not product.unit or target_unit != product.unit.strip():
        raise ValueError(
            "Целевая единица должна совпадать с единицей товара в каталоге"
        )

    _validate_non_negative(
        conversion_data["conversion_factor"],
        "conversion_factor",
    )

    factor = Decimal(str(conversion_data["conversion_factor"]))

    if factor <= 0:
        raise ValueError("Коэффициент пересчёта должен быть больше нуля")

    now = datetime.now()

    query = db.query(ProductUnitConversionDB).filter(
        ProductUnitConversionDB.product_id == product.id,
        ProductUnitConversionDB.source_unit == source_unit,
        ProductUnitConversionDB.target_unit == target_unit,
    )

    if supplier_id is None:
        query = query.filter(
            ProductUnitConversionDB.supplier_id.is_(None)
        )
    else:
        query = query.filter(
            ProductUnitConversionDB.supplier_id == supplier_id
        )

    existing = query.first()

    data = {
        "product_id": product.id,
        "supplier_id": supplier_id,
        "source_unit": source_unit,
        "target_unit": target_unit,
        "conversion_factor": factor,
        "updated_at": now,
    }

    if existing is not None:
        return _save_record(db, existing, data), "updated"

    data["created_at"] = now

    conversion = ProductUnitConversionDB()

    return _save_record(db, conversion, data), "created"


def get_product_unit_conversion(
    db: Session,
    product_id: int,
    source_unit: str,
    target_unit: str,
    supplier_id: int = None,
):
    """Ищет коэффициент: сначала поставщика, затем общий."""

    product = db.get(ProductDB, product_id)

    if product is None:
        raise ValueError("Товар не найден")

    if not product.unit or target_unit.strip() != product.unit.strip():
        raise ValueError(
            "Целевая единица должна совпадать с единицей товара в каталоге"
        )

    query = db.query(ProductUnitConversionDB).filter(
        ProductUnitConversionDB.product_id == product_id,
        ProductUnitConversionDB.source_unit == source_unit.strip(),
        ProductUnitConversionDB.target_unit == target_unit.strip(),
    )

    if supplier_id is not None:
        if db.get(SupplierDB, supplier_id) is None:
            raise ValueError("Поставщик не найден")

        supplier_conversion = query.filter(
            ProductUnitConversionDB.supplier_id == supplier_id
        ).first()

        if supplier_conversion is not None:
            return supplier_conversion

    return query.filter(
        ProductUnitConversionDB.supplier_id.is_(None)
    ).first()


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
        "unit",
        "available_quantity",
        "availability_status",
        "delivery_time_days",
        "payment_terms",
        "delivery_cost",
        "received_at",
        "valid_until",
        "source_type",
        "source_reference",
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

    offer = SupplierOfferDB(**offer_data, verification_status="Не проверено")

    try:
        db.add(offer)
        db.commit()
        db.refresh(offer)

        return offer

    except Exception:
        db.rollback()
        raise



def verify_supplier_offer(
    db: Session,
    offer_id: int,
    verification_status: str,
    verified_by: str = None,
    notes: str = None,
    verified_at: datetime = None,
):
    """Изменяет статус предложения и сохраняет отдельную запись аудита."""

    allowed_statuses = {"Подтверждено", "Отклонено"}

    if verification_status not in allowed_statuses:
        raise ValueError(
            "verification_status должен быть 'Подтверждено' или 'Отклонено'"
        )

    if verified_by is not None and not isinstance(verified_by, str):
        raise ValueError("verified_by должен быть строкой")

    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes должны быть строкой")

    if verified_at is None:
        verified_at = datetime.now()
    elif not isinstance(verified_at, datetime):
        raise ValueError("verified_at должен быть объектом datetime")

    offer = db.get(SupplierOfferDB, offer_id)

    if offer is None:
        raise ValueError("Предложение поставщика не найдено")

    verification = SupplierOfferVerificationDB(
        offer_id=offer.id,
        verification_status=verification_status,
        verified_at=verified_at,
        verified_by=verified_by.strip() or None if verified_by is not None else None,
        notes=notes,
    )

    try:
        offer.verification_status = verification_status
        db.add(verification)
        db.commit()
        db.refresh(offer)
        db.refresh(verification)

        return verification

    except Exception:
        db.rollback()
        raise
def get_all_supplier_offers(
    db: Session,
    supplier_id: int = None,
    product_id: int = None,
):
    """Возвращает все предложения, включая предложения с истёкшим сроком."""

    query = db.query(SupplierOfferDB)

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


def compare_supplier_offers(
    db: Session,
    product_id: int,
    required_quantity,
):
    """Сравнивает актуальные предложения по полной стоимости закупки."""

    try:
        quantity = Decimal(str(required_quantity))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Некорректное требуемое количество")

    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("Требуемое количество должно быть больше нуля")

    product = db.get(ProductDB, product_id)

    if product is None:
        raise ValueError("Товар не найден")

    if not product.unit:
        raise ValueError("У товара не указана единица измерения")

    def normalize_quantity(value, source_unit, target_unit, supplier_id):
        source_name = " ".join(source_unit.lower().strip().split())
        target_name = " ".join(target_unit.lower().strip().split())

        source_definition = get_unit_definition(source_name)
        target_definition = get_unit_definition(target_name)

        if source_definition and target_definition:
            source_family, source_factor, _ = source_definition
            target_family, target_factor, _ = target_definition

            if source_family != target_family:
                raise ValueError(
                    "Нельзя пересчитывать единицы разных физических категорий"
                )

            return value * source_factor / target_factor

        if source_name == target_name:
            return value

        conversion = get_product_unit_conversion(
            db=db,
            product_id=product_id,
            source_unit=source_unit,
            target_unit=target_unit,
            supplier_id=supplier_id,
        )

        if conversion is None:
            raise ValueError(
                f"Не найден коэффициент пересчёта: "
                f"{source_unit} → {target_unit}"
            )

        factor = Decimal(str(conversion.conversion_factor))

        if not factor.is_finite() or factor <= 0:
            raise ValueError("Некорректный коэффициент пересчёта")

        return value * factor

    ranked_offers = []
    unranked_offers = []
    expired_offers = []
    expired_unranked_offers = []

    offers = get_all_supplier_offers(
        db=db,
        product_id=product_id,
    )

    for offer in offers:
        if offer.verification_status == "Отклонено":
            continue

        is_expired = (
            offer.valid_until is not None
            and offer.valid_until < datetime.now()
        )
        freshness_status = (
            "Требуется перепроверка"
            if is_expired
            else "Срок не указан"
            if offer.valid_until is None
            else "Не просрочено"
        )
        freshness_warning = (
            "Требуется уточнить у поставщика актуальность цены и наличия"
            if is_expired
            else None
        )

        supplier = db.get(SupplierDB, offer.supplier_id)

        def add_unranked(reason):
            target = expired_unranked_offers if is_expired else unranked_offers
            target.append({
                "offer": offer,
                "supplier": supplier,
                "reason": reason,
                "freshness_status": freshness_status,
                "freshness_warning": freshness_warning,
            })

        if not offer.unit:
            add_unranked("У предложения не указана единица измерения")
            continue

        if offer.available_quantity is None:
            add_unranked("Количество у поставщика не указано")
            continue

        if offer.delivery_cost is None:
            add_unranked("Стоимость доставки не указана")
            continue

        try:
            available = Decimal(str(offer.available_quantity))
            delivery_cost = Decimal(str(offer.delivery_cost))

            if not available.is_finite() or available < 0:
                raise ValueError("Некорректное доступное количество")

            if not delivery_cost.is_finite() or delivery_cost < 0:
                raise ValueError("Некорректная стоимость доставки")

            available_target = normalize_quantity(
                available,
                offer.unit,
                product.unit,
                offer.supplier_id,
            )

            if available_target < quantity:
                add_unranked("Недостаточно товара у поставщика")
                continue

            normalized_price = normalize_unit_price(
                price=offer.price,
                source_unit=offer.unit,
                target_unit=product.unit,
                db=db,
                product_id=product_id,
                supplier_id=offer.supplier_id,
            )

        except (ValueError, InvalidOperation, TypeError) as exc:
            add_unranked(str(exc))
            continue

        goods_total = normalized_price * quantity
        landed_total = goods_total + delivery_cost

        target = expired_offers if is_expired else ranked_offers
        target.append({
            "offer": offer,
            "supplier": supplier,
            "normalized_unit_price": normalized_price,
            "goods_total": goods_total,
            "delivery_cost": delivery_cost,
            "landed_total": landed_total,
            "verification_status": offer.verification_status,
            "available_quantity": available_target,
            "freshness_status": freshness_status,
            "freshness_warning": freshness_warning,
        })

    ranked_offers.sort(key=lambda item: item["landed_total"])
    expired_offers.sort(key=lambda item: item["landed_total"])

    return {
        "ranked_offers": ranked_offers,
        "unranked_offers": unranked_offers,
        "expired_offers": expired_offers,
        "expired_unranked_offers": expired_unranked_offers,
    }
