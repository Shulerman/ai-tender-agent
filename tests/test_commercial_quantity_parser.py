from decimal import Decimal

import pytest

from app.ai.technical_models import ProductAnalysis
from app.commercial.quantity_parser import parse_product_quantity


@pytest.mark.parametrize(
    ("quantity", "unit", "expected_quantity", "expected_status"),
    [
        ("500", "кг", Decimal("500"), "parsed"),
        ("500 кг", "кг", Decimal("500"), "parsed"),
        ("1 250 кг", "кг", Decimal("1250"), "parsed"),
        ("2,5 кг", "кг", Decimal("2.5"), "parsed"),
        ("500 шт.", "шт.", Decimal("500"), "parsed"),
        ("500 ед.", "шт.", Decimal("500"), "parsed"),
        ("500 единиц", "ед.", Decimal("500"), "parsed"),
        ("500 г", "кг", None, "ambiguous"),
        ("от 500 кг", "кг", None, "ambiguous"),
        ("500–700 кг", "кг", None, "ambiguous"),
        ("около 500 кг", "кг", None, "ambiguous"),
        ("1.250 кг", "кг", None, "ambiguous"),
    ],
)
def test_parse_product_quantity(
    quantity,
    unit,
    expected_quantity,
    expected_status,
):
    product = ProductAnalysis(
        name="Тестовый товар",
        quantity=quantity,
        unit=unit,
    )

    result = parse_product_quantity(product)

    assert result["estimated_quantity"] == expected_quantity
    assert result["parse_status"] == expected_status
    assert result["source_quantity"] == quantity
    assert result["source_unit"] == unit


@pytest.mark.parametrize(
    "quantity",
    [
        "",
        "Не указано",
        "не определено",
        "неизвестно",
        "по заявкам",
        "по потребности",
        "по мере необходимости",
    ],
)
def test_missing_quantity(quantity):
    product = ProductAnalysis(
        name="Тестовый товар",
        quantity=quantity,
        unit="шт.",
    )

    result = parse_product_quantity(product)

    assert result["estimated_quantity"] is None
    assert result["parse_status"] == "missing"


@pytest.mark.parametrize("quantity", ["0", "-5", "NaN", "Infinity"])
def test_invalid_numeric_quantity(quantity):
    product = ProductAnalysis(
        name="Тестовый товар",
        quantity=quantity,
        unit="шт.",
    )

    result = parse_product_quantity(product)

    assert result["estimated_quantity"] is None
    assert result["parse_status"] == "ambiguous"


def test_parser_rejects_wrong_input_type():
    with pytest.raises(TypeError):
        parse_product_quantity({"name": "Товар", "quantity": "500", "unit": "шт."})