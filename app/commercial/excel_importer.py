from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from openpyxl import load_workbook


FIELD_ALIASES = {
    "name": [
        "наименование",
        "название",
        "товар",
        "продукция",
        "номенклатура",
        "name",
        "product",
        "item",
    ],
    "article_number": [
        "артикул",
        "код товара",
        "код",
        "sku",
        "article",
        "part number",
    ],
    "supplier_article_number": [
        "артикул поставщика",
        "код поставщика",
        "supplier article",
        "supplier article number",
        "supplier sku",
    ],
    "price": [
        "цена",
        "стоимость",
        "цена за единицу",
        "оптовая цена",
        "price",
        "unit price",
    ],
    "currency": [
        "валюта",
        "currency",
    ],
    "unit": [
        "единица",
        "ед изм",
        "ед. изм.",
        "единица измерения",
        "unit",
    ],
    "available_quantity": [
        "остаток",
        "количество",
        "наличие",
        "доступное количество",
        "available quantity",
        "stock",
        "quantity",
    ],
    "valid_until": [
        "действует до",
        "срок действия",
        "дата окончания",
        "valid until",
        "expiry date",
    ],
    "delivery_time_days": [
        "срок поставки",
        "доставка дней",
        "срок доставки",
        "delivery time",
    ],
}

REQUIRED_FIELDS = {"name", "price"}

ALLOWED_FIELDS = set(FIELD_ALIASES)


def _normalize_header(value):
    """Нормализует название столбца для поиска совпадений."""

    if value is None:
        return ""

    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("ё", "е")

    return text


def _suggest_mapping(headers):
    """Предлагает сопоставление известных названий столбцов."""

    mapping = {}

    for column_index, header in enumerate(headers, start=1):
        normalized = _normalize_header(header)

        if not normalized:
            continue

        for field, aliases in FIELD_ALIASES.items():
            normalized_aliases = {
                _normalize_header(alias)
                for alias in aliases
            }

            if normalized in normalized_aliases:
                if field not in mapping:
                    mapping[field] = column_index

    return mapping



def _validate_header_row(header_row):
    """Проверяет номер строки заголовка."""

    if (
        not isinstance(header_row, int)
        or isinstance(header_row, bool)
        or header_row < 1
    ):
        raise ValueError(
            "header_row должен быть положительным целым числом"
        )


def inspect_price_list(
    file_path,
    sheet_name=None,
    header_row=1,
    sample_size=5,
):
    """
    Анализирует структуру Excel-файла.

    Возвращает названия листов, заголовки, примеры строк
    и предварительное сопоставление столбцов.
    """

    _validate_header_row(header_row)

    path = Path(file_path)

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(
            "Поддерживаются только файлы XLSX и XLSM"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"Файл не найден: {path}"
        )

    if not isinstance(header_row, int) or header_row < 1:
        raise ValueError("header_row должен быть положительным числом")

    if not isinstance(sample_size, int) or sample_size < 1:
        raise ValueError("sample_size должен быть положительным числом")

    workbook = load_workbook(
        filename=path,
        read_only=True,
        data_only=True,
    )

    try:
        sheet_names = workbook.sheetnames

        if sheet_name is None:
            selected_sheet = sheet_names[0]
        else:
            if sheet_name not in sheet_names:
                raise ValueError(
                    f"Лист не найден: {sheet_name}"
                )

            selected_sheet = sheet_name

        worksheet = workbook[selected_sheet]

        header_values = next(
            worksheet.iter_rows(
                min_row=header_row,
                max_row=header_row,
                values_only=True,
            ),
            (),
        )

        headers = list(header_values)

        if not headers or not any(
            value is not None for value in headers
        ):
            raise ValueError(
                "В указанной строке не найдены заголовки"
            )

        sample_rows = []

        for row_number, row in enumerate(
            worksheet.iter_rows(
                min_row=header_row + 1,
                max_row=header_row + sample_size,
                values_only=True,
            ),
            start=header_row + 1,
        ):
            if not any(value is not None for value in row):
                continue

            sample_rows.append({
                "source_row": row_number,
                "values": list(row),
            })

        return {
            "file_name": path.name,
            "sheet_names": sheet_names,
            "selected_sheet": selected_sheet,
            "header_row": header_row,
            "headers": headers,
            "suggested_mapping": _suggest_mapping(headers),
            "sample_rows": sample_rows,
        }

    finally:
        workbook.close()


def _get_cell_value(row, column_index):
    """Получает значение по номеру столбца, начиная с единицы."""

    if column_index is None:
        return None

    if not isinstance(column_index, int) or column_index < 1:
        raise ValueError(
            "Номер столбца должен быть положительным целым числом"
        )

    if column_index > len(row):
        return None

    return row[column_index - 1]


def _parse_decimal(value, field_name):
    """Parse a finite non-negative Decimal value."""

    if value is None or value == "":
        return None

    if isinstance(value, bool):
        raise ValueError(
            f"\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 "
            f"\u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0435 "
            f"\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435: {field_name}"
        )

    try:
        if isinstance(value, str):
            normalized = (
                value.strip()
                .replace("\u00a0", "")
                .replace("\u202f", "")
                .replace(" ", "")
            )

            if "," in normalized and "." in normalized:
                if normalized.rfind(",") > normalized.rfind("."):
                    normalized = normalized.replace(".", "")
                    normalized = normalized.replace(",", ".")
                else:
                    normalized = normalized.replace(",", "")
            elif "," in normalized or "." in normalized:
                separator = "," if "," in normalized else "."
                integer_part, fractional_part = normalized.split(separator)

                if (
                    len(fractional_part) == 3
                    and integer_part.lstrip("+-").isdigit()
                    and 1 <= len(integer_part.lstrip("+-")) <= 3
                    and fractional_part.isdigit()
                ):
                    raise ValueError(
                        f"Ambiguous numeric format: {value}. "
                        "Please verify the decimal and thousands separator."
                    )

                normalized = normalized.replace(",", ".")

            number = Decimal(normalized)
        else:
            number = Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 "
            f"\u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0435 "
            f"\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435: {field_name}"
        )

    if not number.is_finite():
        raise ValueError(
            f"\u041f\u043e\u043b\u0435 {field_name} "
            f"\u0434\u043e\u043b\u0436\u043d\u043e \u0431\u044b\u0442\u044c "
            f"\u043a\u043e\u043d\u0435\u0447\u043d\u044b\u043c \u0447\u0438\u0441\u043b\u043e\u043c"
        )

    if number < 0:
        raise ValueError(
            f"\u041f\u043e\u043b\u0435 {field_name} "
            f"\u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c "
            f"\u043e\u0442\u0440\u0438\u0446\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u043c"
        )

    return number


def _parse_date(value):
    """Parse Excel dates and common date strings."""

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    if isinstance(value, str):
        normalized = value.strip()

        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass

        for date_format in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(normalized, date_format)
            except ValueError:
                continue

        raise ValueError(
            f"\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u0430\u044f "
            f"\u0434\u0430\u0442\u0430: {value}"
        )

    raise ValueError(
        f"\u041d\u0435\u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u043c\u044b\u0439 "
        f"\u0444\u043e\u0440\u043c\u0430\u0442 \u0434\u0430\u0442\u044b: {value}"
    )


def parse_price_list(
    file_path,
    column_mapping,
    sheet_name=None,
    header_row=1,
    default_currency="RUB",
):
    """
    Извлекает товарные предложения из Excel.

    column_mapping:
        Словарь с номерами столбцов, начиная с единицы.

    Обязательные поля:
        name, price.

    Возвращает корректные строки и ошибки отдельно.
    Все импортированные цены считаются непроверенными.
    """

    _validate_header_row(header_row)

    if not isinstance(column_mapping, dict):
        raise ValueError(
            "column_mapping должен быть словарём"
        )

    unknown_fields = set(column_mapping) - ALLOWED_FIELDS

    if unknown_fields:
        raise ValueError(
            "Неизвестные поля сопоставления: "
            + ", ".join(sorted(unknown_fields))
        )

    missing_fields = REQUIRED_FIELDS - set(column_mapping)

    if missing_fields:
        raise ValueError(
            "Не сопоставлены обязательные поля: "
            + ", ".join(sorted(missing_fields))
        )

    for field, column_index in column_mapping.items():
        if (
            not isinstance(column_index, int)
            or isinstance(column_index, bool)
            or column_index < 1
        ):
            raise ValueError(
                f"Некорректный номер столбца для поля {field}"
            )

    if (
        not isinstance(default_currency, str)
        or len(default_currency.strip()) != 3
    ):
        raise ValueError(
            "Валюта по умолчанию должна состоять из трёх символов"
        )

    path = Path(file_path)

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(
            "Поддерживаются только файлы XLSX и XLSM"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"Файл не найден: {path}"
        )

    workbook = load_workbook(
        filename=path,
        read_only=True,
        data_only=True,
    )

    try:
        if sheet_name is None:
            selected_sheet = workbook.sheetnames[0]
        else:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(
                    f"Лист не найден: {sheet_name}"
                )

            selected_sheet = sheet_name

        worksheet = workbook[selected_sheet]

        imported_rows = []
        errors = []

        for row_number, row in enumerate(
            worksheet.iter_rows(
                min_row=header_row + 1,
                values_only=True,
            ),
            start=header_row + 1,
        ):
            if not any(value is not None for value in row):
                continue

            try:
                name_value = _get_cell_value(
                    row,
                    column_mapping["name"],
                )

                price_value = _get_cell_value(
                    row,
                    column_mapping["price"],
                )

                if name_value is None or not str(name_value).strip():
                    raise ValueError("Не указано название товара")

                if price_value is None or price_value == "":
                    raise ValueError("Не указана цена")

                price = _parse_decimal(price_value, "price")

                if price is None:
                    raise ValueError("Не указана цена")

                article_number = _get_cell_value(
                    row,
                    column_mapping.get("article_number"),
                )

                supplier_article_number = _get_cell_value(
                    row,
                    column_mapping.get("supplier_article_number"),
                )

                source_article_number = (
                    supplier_article_number
                    if (
                        supplier_article_number is not None
                        and str(supplier_article_number).strip()
                    )
                    else article_number
                )

                unit = _get_cell_value(
                    row,
                    column_mapping.get("unit"),
                )

                currency = _get_cell_value(
                    row,
                    column_mapping.get("currency"),
                )

                quantity_value = _get_cell_value(
                    row,
                    column_mapping.get("available_quantity"),
                )

                valid_until_value = _get_cell_value(
                    row,
                    column_mapping.get("valid_until"),
                )

                delivery_days_value = _get_cell_value(
                    row,
                    column_mapping.get("delivery_time_days"),
                )

                quantity = _parse_decimal(
                    quantity_value,
                    "available_quantity",
                )

                valid_until = _parse_date(valid_until_value)

                delivery_days = None

                if delivery_days_value not in (None, ""):
                    delivery_decimal = _parse_decimal(
                        delivery_days_value,
                        "delivery_time_days",
                    )

                    if (
                        delivery_decimal != delivery_decimal.to_integral_value()
                    ):
                        raise ValueError(
                            "Срок поставки должен быть целым числом дней"
                        )

                    delivery_days = int(delivery_decimal)

                if currency is None or not str(currency).strip():
                    currency = default_currency
                else:
                    currency = str(currency).strip().upper()

                if len(currency) != 3:
                    raise ValueError(
                        "Код валюты должен состоять из трёх символов"
                    )

                imported_rows.append({
                    "source_row": row_number,
                    "source_file": path.name,
                    "source_name": str(name_value).strip(),
                    "source_article_number": (
                        str(source_article_number).strip()
                        if source_article_number is not None
                        else None
                    ),
                    "name": str(name_value).strip(),
                    "article_number": (
                        str(article_number).strip()
                        if article_number is not None
                        else None
                    ),
                    "price": price,
                    "currency": currency,
                    "unit": (
                        str(unit).strip()
                        if unit is not None
                        else None
                    ),
                    "available_quantity": quantity,
                    "valid_until": valid_until,
                    "delivery_time_days": delivery_days,
                    "verification_status": "Не проверено",
                })

            except (ValueError, TypeError) as exc:
                errors.append({
                    "source_row": row_number,
                    "error": str(exc),
                    "values": list(row),
                })

        return {
            "file_name": path.name,
            "sheet_name": selected_sheet,
            "imported_count": len(imported_rows),
            "error_count": len(errors),
            "items": imported_rows,
            "errors": errors,
        }

    finally:
        workbook.close()
