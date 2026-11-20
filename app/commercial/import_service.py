import re
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.commercial.excel_importer import parse_price_list
from app.commercial.models import (
    ProductDB,
    PriceListImportDB,
    PriceListImportRowDB,
    SupplierDB,
    SupplierOfferDB,
    SupplierProductMappingDB,
)


def _normalize(value):
    """Нормализует строки для точного сопоставления."""

    if value is None:
        return ""

    text = str(value).strip().casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def _json_safe(value):
    """Преобразует значения Excel в типы, совместимые с JSON."""

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def _get_raw_rows(file_path, sheet_name, source_rows):
    """Читает исходные значения Excel для сохранения строк."""

    workbook = load_workbook(
        filename=file_path,
        read_only=True,
        data_only=True,
    )

    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(
                f"Лист Excel не найден: {sheet_name}"
            )

        worksheet = workbook[sheet_name]
        result = {}

        for row_number in source_rows:
            result[row_number] = _json_safe(
                list(
                    next(
                        worksheet.iter_rows(
                            min_row=row_number,
                            max_row=row_number,
                            values_only=True,
                        ),
                        (),
                    )
                )
            )

        return result

    finally:
        workbook.close()


def _get_mapped_value(raw_values, column_mapping, field):
    """Получает исходное значение по номеру столбца из mapping."""

    column_number = column_mapping.get(field)

    if (
        not isinstance(column_number, int)
        or isinstance(column_number, bool)
        or column_number < 1
    ):
        return None

    index = column_number - 1

    if index >= len(raw_values):
        return None

    value = raw_values[index]

    if value is None:
        return None

    return str(value).strip() or None


def _find_existing_product(products, article_number, name):
    """
    Ищет существующий товар.

    Приоритет:
    1. Точное нормализованное совпадение артикула.
    2. Если по артикулу нет совпадений — точное совпадение названия.

    Несколько совпадений не разрешаются автоматически.
    """

    normalized_article = _normalize(article_number)

    if normalized_article:
        article_matches = [
            product
            for product in products
            if _normalize(product.article_number) == normalized_article
        ]

        if len(article_matches) == 1:
            return article_matches[0]

        if len(article_matches) > 1:
            return None

    normalized_name = _normalize(name)

    if not normalized_name:
        return None

    name_matches = [
        product
        for product in products
        if _normalize(product.name) == normalized_name
    ]

    if len(name_matches) == 1:
        return name_matches[0]

    return None


def import_price_list(
    db: Session,
    *,
    supplier_id: int,
    file_path: str,
    column_mapping: dict,
    header_row: int = 1,
    sheet_name: str = None,
    file_hash: str = None,
):
    """
    Импортирует Excel-прайс поставщика одной транзакцией.

    Новые товары автоматически не создаются.
    Предложения создаются только для однозначно найденных товаров.
    """

    supplier = db.get(SupplierDB, supplier_id)

    if supplier is None:
        raise ValueError("Поставщик не найден")

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("Путь к файлу не должен быть пустым")

    if not isinstance(column_mapping, dict):
        raise ValueError("column_mapping должен быть словарём")

    parsed = parse_price_list(
        file_path,
        column_mapping=column_mapping,
        sheet_name=sheet_name,
        header_row=header_row,
    )

    selected_sheet = parsed["sheet_name"]
    items = parsed["items"]
    errors = parsed["errors"]

    source_numbers = {
        item["source_row"]
        for item in items
    }

    source_numbers.update(
        item["source_row"]
        for item in errors
    )

    raw_rows = _get_raw_rows(
        file_path,
        selected_sheet,
        source_numbers,
    )

    products = db.query(ProductDB).all()
    now = datetime.now()

    import_record = PriceListImportDB(
        supplier_id=supplier_id,
        file_name=parsed["file_name"],
        file_path=file_path,
        file_hash=file_hash,
        sheet_name=selected_sheet,
        header_row=header_row,
        column_mapping=column_mapping,
        status="В обработке",
        total_rows=len(items) + len(errors),
        imported_rows=0,
        error_rows=0,
        errors=None,
        created_at=now,
    )

    created_offers = 0
    saved_rows = 0
    saved_errors = []

    try:
        db.add(import_record)
        db.flush()

        for item in items:
            source_row = item["source_row"]
            raw_values = raw_rows.get(source_row, [])

            normalized_article = _normalize(
                item.get("source_article_number")
                or item.get("article_number")
            )

            mapping = None
            if normalized_article:
                mapping = (
                    db.query(SupplierProductMappingDB)
                    .filter_by(
                        supplier_id=supplier_id,
                        normalized_supplier_article_number=normalized_article,
                    )
                    .first()
                )

            if mapping is not None:
                mapped_product = db.get(ProductDB, mapping.product_id)
                catalog_article = _normalize(item.get("article_number"))

                if mapped_product is None:
                    product = None
                elif catalog_article:
                    article_matches = [
                        candidate
                        for candidate in products
                        if _normalize(candidate.article_number) == catalog_article
                    ]

                    if len(article_matches) == 0:
                        product = mapped_product
                    elif (
                        len(article_matches) == 1
                        and article_matches[0].id == mapped_product.id
                    ):
                        product = mapped_product
                    else:
                        product = None
                else:
                    product = mapped_product
            else:
                product = _find_existing_product(
                    products,
                    item.get("article_number"),
                    item.get("name"),
                )

            row_status = (
                "Сопоставлен"
                if product is not None
                else "Требует сопоставления"
            )

            import_row = PriceListImportRowDB(
                import_id=import_record.id,
                source_row=source_row,
                source_values=raw_values,
                source_name=item.get("source_name") or item.get("name"),
                source_article_number=(
                    item.get("source_article_number")
                    or item.get("article_number")
                ),
                price=item["price"],
                currency=item.get("currency") or "RUB",
                unit=item.get("unit"),
                available_quantity=item.get("available_quantity"),
                valid_until=item.get("valid_until"),
                delivery_time_days=item.get("delivery_time_days"),
                product_id=product.id if product is not None else None,
                status=row_status,
                error=None,
                created_at=now,
            )

            db.add(import_row)
            saved_rows += 1

            if product is None:
                continue

            source_reference = (
                f'{parsed["file_name"]}; '
                f'лист: {selected_sheet}; '
                f'строка: {source_row}'
            )

            offer = SupplierOfferDB(
                supplier_id=supplier_id,
                import_id=import_record.id,
                product_id=product.id,
                price=item["price"],
                currency=item.get("currency") or "RUB",
                unit=item.get("unit"),
                available_quantity=item.get("available_quantity"),
                availability_status=None,
                delivery_time_days=item.get("delivery_time_days"),
                received_at=now,
                valid_until=item.get("valid_until"),
                source_type="Excel",
                source_reference=source_reference,
                verification_status="Не проверено",
            )

            db.add(offer)
            created_offers += 1

        for error_item in errors:
            source_row = error_item["source_row"]
            raw_values = raw_rows.get(source_row, [])

            import_row = PriceListImportRowDB(
                import_id=import_record.id,
                source_row=source_row,
                source_values=raw_values,
                source_name=_get_mapped_value(
                    raw_values,
                    column_mapping,
                    "name",
                ),
                source_article_number=_get_mapped_value(
                    raw_values,
                    column_mapping,
                    "article_number",
                ),
                price=None,
                currency=None,
                unit=None,
                available_quantity=None,
                valid_until=None,
                delivery_time_days=None,
                product_id=None,
                status="Ошибка",
                error=error_item["error"],
                created_at=now,
            )

            db.add(import_row)

            saved_errors.append(
                _json_safe(error_item)
            )

        import_record.imported_rows = saved_rows
        import_record.error_rows = len(errors)
        import_record.errors = saved_errors
        import_record.status = (
            "Завершён с ошибками"
            if errors
            else "Завершён"
        )
        import_record.completed_at = datetime.now()

        db.commit()
        db.refresh(import_record)

        return {
            "import_id": import_record.id,
            "supplier_id": supplier_id,
            "file_name": import_record.file_name,
            "sheet_name": selected_sheet,
            "status": import_record.status,
            "total_rows": import_record.total_rows,
            "imported_rows": import_record.imported_rows,
            "error_rows": import_record.error_rows,
            "matched_offers": created_offers,
            "unmatched_rows": saved_rows - created_offers,
            "errors": saved_errors,
        }

    except Exception:
        db.rollback()
        raise
def match_import_row(
    db,
    *,
    import_id: int,
    row_id: int,
    product_id: int,
):
    """Вручную связывает строку импорта с товаром каталога."""

    try:
        import_record = (
            db.query(PriceListImportDB)
            .filter(PriceListImportDB.id == import_id)
            .first()
        )
        if import_record is None:
            raise ValueError("Импорт не найден.")

        import_row = (
            db.query(PriceListImportRowDB)
            .filter(
                PriceListImportRowDB.id == row_id,
                PriceListImportRowDB.import_id == import_id,
            )
            .with_for_update()
            .first()
        )
        if import_row is None:
            raise ValueError("Строка не найдена в указанном импорте.")

        if import_row.status != "Требует сопоставления":
            raise ValueError("Строка уже обработана или не требует сопоставления.")

        product = (
            db.query(ProductDB)
            .filter(ProductDB.id == product_id)
            .first()
        )
        if product is None:
            raise ValueError("Товар каталога не найден.")

        if import_row.price is None:
            raise ValueError("Нельзя создать предложение: в строке отсутствует цена.")

        normalized_article = _normalize(
            import_row.source_article_number
        )

        if normalized_article:
            mapping = (
                db.query(SupplierProductMappingDB)
                .filter_by(
                    supplier_id=import_record.supplier_id,
                    normalized_supplier_article_number=normalized_article,
                )
                .with_for_update()
                .first()
            )

            if mapping is not None:
                if mapping.product_id != product.id:
                    raise ValueError(
                        "Артикул этого поставщика уже связан с другим "
                        "товаром каталога. Изменение связи требует "
                        "отдельного подтверждения."
                    )
            else:
                now = datetime.now()
                mapping = SupplierProductMappingDB(
                    supplier_id=import_record.supplier_id,
                    supplier_article_number=str(
                        import_row.source_article_number
                    ),
                    normalized_supplier_article_number=normalized_article,
                    product_id=product.id,
                    supplier_product_name=import_row.source_name,
                    created_at=now,
                    updated_at=now,
                )
                db.add(mapping)

        offer = SupplierOfferDB(
            supplier_id=import_record.supplier_id,
            import_id=import_record.id,
            product_id=product.id,
            price=import_row.price,
            currency=import_row.currency or "RUB",
            unit=import_row.unit,
            available_quantity=import_row.available_quantity,
            delivery_time_days=import_row.delivery_time_days,
            received_at=datetime.now(),
            valid_until=import_row.valid_until,
            source_type="Excel",
            source_reference=(
                f"{import_record.file_name}; "
                f"лист: {import_record.sheet_name or 'не указан'}; "
                f"строка: {import_row.source_row}"
            ),
            verification_status="Не проверено",
        )

        import_row.product_id = product.id
        import_row.status = "Сопоставлен"
        import_row.error = None

        db.add(offer)
        db.commit()
        db.refresh(offer)
        db.refresh(import_row)

        return {
            "import_id": import_record.id,
            "row_id": import_row.id,
            "product_id": product.id,
            "offer_id": offer.id,
            "status": import_row.status,
        }

    except Exception:
        db.rollback()
        raise
