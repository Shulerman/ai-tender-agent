from decimal import Decimal

import pytest

from app.commercial.calculator import calculate_commercial_result


def test_calculate_complete_commercial_result():
    result = calculate_commercial_result(
        contract_revenue="100000",
        items=[
            {
                "name": "Товар 1",
                "quantity": 10,
                "unit_price": "500",
                "price_verified": True,
            },
            {
                "name": "Товар 2",
                "quantity": 5,
                "unit_price": "2000",
                "price_verified": True,
            },
        ],
        additional_costs="5000",
    )

    assert result["calculation_status"] == "complete"
    assert result["contract_revenue"] == Decimal("100000")
    assert result["total_purchase_cost"] == Decimal("15000")
    assert result["additional_costs"] == Decimal("5000")
    assert result["gross_profit"] == Decimal("80000")
    assert result["gross_margin_percent"] == Decimal("80")


def test_missing_contract_revenue():
    result = calculate_commercial_result(
        contract_revenue=None,
        items=[
            {
                "name": "Товар",
                "quantity": 10,
                "unit_price": 500,
                "price_verified": True,
            }
        ],
        additional_costs=1000,
    )

    assert result["calculation_status"] == "incomplete"
    assert result["gross_profit"] is None
    assert result["gross_margin_percent"] is None
    assert result["total_purchase_cost"] == Decimal("5000")


def test_missing_additional_costs():
    result = calculate_commercial_result(
        contract_revenue=10000,
        items=[
            {
                "name": "Товар",
                "quantity": 2,
                "unit_price": 1000,
                "price_verified": True,
            }
        ],
        additional_costs=None,
    )

    assert result["calculation_status"] == "incomplete"
    assert result["gross_profit"] is None
    assert result["gross_margin_percent"] is None


def test_unverified_supplier_price():
    result = calculate_commercial_result(
        contract_revenue=10000,
        items=[
            {
                "name": "Товар",
                "quantity": 2,
                "unit_price": 1000,
                "price_verified": False,
            }
        ],
        additional_costs=500,
    )

    assert result["calculation_status"] == "incomplete"
    assert result["total_purchase_cost"] is None
    assert result["gross_profit"] is None
    assert any(
        "не подтверждена" in message
        for message in result["missing_data"]
    )


@pytest.mark.parametrize(
    "item",
    [
        {
            "name": "Товар",
            "quantity": None,
            "unit_price": 100,
            "price_verified": True,
        },
        {
            "name": "Товар",
            "quantity": 2,
            "unit_price": None,
            "price_verified": True,
        },
    ],
)
def test_missing_item_data(item):
    result = calculate_commercial_result(
        contract_revenue=10000,
        items=[item],
        additional_costs=500,
    )

    assert result["calculation_status"] == "incomplete"
    assert result["total_purchase_cost"] is None
    assert result["gross_profit"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "contract_revenue": -100,
            "items": [
                {
                    "name": "Товар",
                    "quantity": 1,
                    "unit_price": 10,
                    "price_verified": True,
                }
            ],
            "additional_costs": 0,
        },
        {
            "contract_revenue": 100,
            "items": [
                {
                    "name": "Товар",
                    "quantity": -1,
                    "unit_price": 10,
                    "price_verified": True,
                }
            ],
            "additional_costs": 0,
        },
        {
            "contract_revenue": 100,
            "items": [
                {
                    "name": "Товар",
                    "quantity": 1,
                    "unit_price": -10,
                    "price_verified": True,
                }
            ],
            "additional_costs": 0,
        },
        {
            "contract_revenue": 100,
            "items": [
                {
                    "name": "Товар",
                    "quantity": 1,
                    "unit_price": 10,
                    "price_verified": True,
                }
            ],
            "additional_costs": -1,
        },
    ],
)
def test_negative_values_are_rejected(arguments):
    with pytest.raises(ValueError):
        calculate_commercial_result(**arguments)


def test_zero_contract_revenue_does_not_cause_division_by_zero():
    result = calculate_commercial_result(
        contract_revenue=0,
        items=[
            {
                "name": "Товар",
                "quantity": 1,
                "unit_price": 100,
                "price_verified": True,
            }
        ],
        additional_costs=50,
    )

    assert result["calculation_status"] == "complete"
    assert result["gross_profit"] == Decimal("-150")
    assert result["gross_margin_percent"] is None


def test_empty_items_are_rejected():
    with pytest.raises(ValueError):
        calculate_commercial_result(
            contract_revenue=10000,
            items=[],
            additional_costs=500,
        )


def test_invalid_price_verified_type_is_rejected():
    with pytest.raises(ValueError):
        calculate_commercial_result(
            contract_revenue=10000,
            items=[
                {
                    "name": "Товар",
                    "quantity": 1,
                    "unit_price": 100,
                    "price_verified": "Да",
                }
            ],
            additional_costs=500,
        )


def test_unknown_item_fields_are_rejected():
    with pytest.raises(ValueError):
        calculate_commercial_result(
            contract_revenue=10000,
            items=[
                {
                    "name": "Товар",
                    "quantity": 1,
                    "unit_price": 100,
                    "price_verified": True,
                    "unknown_field": "value",
                }
            ],
            additional_costs=500,
        )
