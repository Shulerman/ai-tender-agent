from datetime import datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.commercial.excel_importer import (
    inspect_price_list,
    parse_price_list,
)


@pytest.fixture
def price_list_file(tmp_path):
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
        "Остаток",
        "Действует до",
        "Срок поставки",
    ])

    worksheet.append([
        "A-100",
        "Бумага офисная",
        350.50,
        "RUB",
        "упаковка",
        100,
        datetime(2027, 1, 31),
        5,
    ])

    worksheet.append([
        "B-200",
        "Картридж лазерный",
        "1250,75",
        "RUB",
        "шт.",
        25,
        None,
        3,
    ])

    worksheet.append([
        "C-300",
        "Папка архивная",
        "неизвестно",
        "RUB",
        "шт.",
        50,
        None,
        2,
    ])

    worksheet.append([
        "D-400",
        None,
        100,
        "RUB",
        "шт.",
        10,
        None,
        1,
    ])

    worksheet.append([
        "E-500",
        "Степлер",
        None,
        "RUB",
        "шт.",
        15,
        None,
        2,
    ])

    workbook.save(file_path)
    workbook.close()

    return file_path


def test_inspect_price_list(price_list_file):
    result = inspect_price_list(price_list_file)

    assert result["file_name"] == "supplier_prices.xlsx"
    assert result["selected_sheet"] == "Прайс"
    assert result["suggested_mapping"]["name"] == 2
    assert result["suggested_mapping"]["price"] == 3
    assert result["suggested_mapping"]["article_number"] == 1
    assert len(result["sample_rows"]) == 5


def test_parse_price_list(price_list_file):
    result = parse_price_list(
        price_list_file,
        column_mapping={
            "article_number": 1,
            "name": 2,
            "price": 3,
            "currency": 4,
            "unit": 5,
            "available_quantity": 6,
            "valid_until": 7,
            "delivery_time_days": 8,
        },
    )

    assert result["imported_count"] == 2
    assert result["error_count"] == 3

    first_item = result["items"][0]

    assert first_item["name"] == "Бумага офисная"
    assert first_item["article_number"] == "A-100"
    assert first_item["price"] == Decimal("350.5")
    assert first_item["currency"] == "RUB"
    assert first_item["unit"] == "упаковка"
    assert first_item["available_quantity"] == Decimal("100")
    assert first_item["delivery_time_days"] == 5
    assert first_item["verification_status"] == "Не проверено"


def test_parse_decimal_with_comma(price_list_file):
    result = parse_price_list(
        price_list_file,
        column_mapping={
            "name": 2,
            "price": 3,
        },
    )

    assert result["items"][1]["price"] == Decimal("1250.75")


def test_import_preserves_source_row(price_list_file):
    result = parse_price_list(
        price_list_file,
        column_mapping={
            "name": 2,
            "price": 3,
        },
    )

    assert result["items"][0]["source_row"] == 2
    assert result["items"][1]["source_row"] == 3

    assert result["errors"][0]["source_row"] == 4


def test_invalid_price_is_reported(price_list_file):
    result = parse_price_list(
        price_list_file,
        column_mapping={
            "name": 2,
            "price": 3,
        },
    )

    assert result["error_count"] == 3
    assert "Некорректное числовое значение" in (
        result["errors"][0]["error"]
    )


def test_empty_required_fields_are_reported(price_list_file):
    result = parse_price_list(
        price_list_file,
        column_mapping={
            "name": 2,
            "price": 3,
        },
    )

    errors = [
        item["error"]
        for item in result["errors"]
    ]

    assert any("название товара" in error for error in errors)
    assert any("цена" in error for error in errors)


def test_manual_column_mapping(price_list_file):
    result = parse_price_list(
        price_list_file,
        column_mapping={
            "name": 2,
            "price": 3,
        },
    )

    assert result["imported_count"] == 2
    assert result["items"][0]["name"] == "Бумага офисная"


def test_missing_required_mapping_is_rejected(price_list_file):
    with pytest.raises(ValueError):
        parse_price_list(
            price_list_file,
            column_mapping={
                "name": 2,
            },
        )


def test_unknown_mapping_field_is_rejected(price_list_file):
    with pytest.raises(ValueError):
        parse_price_list(
            price_list_file,
            column_mapping={
                "name": 2,
                "price": 3,
                "unknown": 4,
            },
        )


def test_negative_price_is_reported(tmp_path):
    file_path = tmp_path / "negative_price.xlsx"

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Product name", "Price"])
    worksheet.append(["Test product", -100])
    workbook.save(file_path)
    workbook.close()

    result = parse_price_list(
        file_path,
        column_mapping={
            "name": 1,
            "price": 2,
        },
    )

    assert result["imported_count"] == 0
    assert result["error_count"] == 1
    assert "price" in result["errors"][0]["error"].lower()

def test_unsupported_file_extension_is_rejected(tmp_path):
    file_path = tmp_path / "supplier_prices.csv"
    file_path.write_text("name,price", encoding="utf-8")

    with pytest.raises(ValueError):
        inspect_price_list(file_path)


def test_missing_file_is_reported(tmp_path):
    file_path = tmp_path / "missing.xlsx"

    with pytest.raises(FileNotFoundError):
        inspect_price_list(file_path)


def test_selected_sheet_is_supported(price_list_file):
    result = inspect_price_list(
        price_list_file,
        sheet_name="Прайс",
    )

    assert result["selected_sheet"] == "Прайс"


def test_unknown_sheet_is_rejected(price_list_file):
    with pytest.raises(ValueError):
        inspect_price_list(
            price_list_file,
            sheet_name="Несуществующий лист",
        )

@pytest.mark.parametrize(
    "value, expected",
    [
        ("1250,75", Decimal("1250.75")),
        ("1 250,50", Decimal("1250.50")),
        ("1\u00a0250,50", Decimal("1250.50")),
        ("1\u202f250,50", Decimal("1250.50")),
        ("1.250,50", Decimal("1250.50")),
        ("1,250.50", Decimal("1250.50")),
    ],
)
def test_decimal_common_formats(value, expected):
    from app.commercial.excel_importer import _parse_decimal

    assert _parse_decimal(value, "price") == expected


@pytest.mark.parametrize("value", ["1,234", "1.234"])
def test_decimal_ambiguous_separator_is_rejected(value):
    from app.commercial.excel_importer import _parse_decimal

    with pytest.raises(ValueError):
        _parse_decimal(value, "price")

@pytest.mark.parametrize(
    "value",
    [
        "2026-11-17",
        "17.11.2026",
        "17/11/2026",
        "17-11-2026",
    ],
)
def test_date_common_formats(value):
    from app.commercial.excel_importer import _parse_date

    assert _parse_date(value) == datetime(2026, 11, 17)


@pytest.mark.parametrize("value", ["invalid", "32.13.2026"])
def test_invalid_date_is_rejected(value):
    from app.commercial.excel_importer import _parse_date

    with pytest.raises(ValueError):
        _parse_date(value)

@pytest.mark.parametrize("value", [1, 2, 10])
def test_header_row_accepts_positive_integers(value):
    from app.commercial.excel_importer import _validate_header_row

    _validate_header_row(value)


@pytest.mark.parametrize(
    "value",
    [0, -1, True, False, "1", 1.5, None],
)
def test_header_row_rejects_invalid_values(value):
    from app.commercial.excel_importer import _validate_header_row

    with pytest.raises(ValueError):
        _validate_header_row(value)



def test_supplier_and_catalog_articles_are_parsed_independently(tmp_path):
    from openpyxl import Workbook

    file_path = tmp_path / "separate_articles.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([
        "Артикул поставщика",
        "Артикул",
        "Наименование",
        "Цена",
    ])
    worksheet.append([
        "SUP-001",
        "CAT-001",
        "Тестовый товар",
        125,
    ])
    workbook.save(file_path)
    workbook.close()

    result = parse_price_list(
        file_path,
        column_mapping={
            "supplier_article_number": 1,
            "article_number": 2,
            "name": 3,
            "price": 4,
        },
    )

    assert result["imported_count"] == 1
    item = result["items"][0]
    assert item["source_article_number"] == "SUP-001"
    assert item["article_number"] == "CAT-001"


def test_legacy_article_column_is_used_for_both_article_fields(tmp_path):
    from openpyxl import Workbook

    file_path = tmp_path / "legacy_article.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Артикул", "Наименование", "Цена"])
    worksheet.append(["A-100", "Тестовый товар", 125])
    workbook.save(file_path)
    workbook.close()

    result = parse_price_list(
        file_path,
        column_mapping={
            "article_number": 1,
            "name": 2,
            "price": 3,
        },
    )

    assert result["imported_count"] == 1
    item = result["items"][0]
    assert item["article_number"] == "A-100"
    assert item["source_article_number"] == "A-100"
