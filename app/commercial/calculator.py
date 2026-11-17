from decimal import Decimal, InvalidOperation


def _to_decimal(value, field_name):
    """Преобразует значение в Decimal и проверяет корректность."""

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Некорректное значение: {field_name}")

    if not number.is_finite():
        raise ValueError(f"Поле {field_name} должно быть конечным числом")

    return number


def _validate_non_negative(value, field_name):
    number = _to_decimal(value, field_name)

    if number < 0:
        raise ValueError(
            f"Поле {field_name} не может быть отрицательным"
        )

    return number


def calculate_commercial_result(
    contract_revenue,
    items,
    additional_costs=None,
):
    """
    Рассчитывает экономику тендера.

    contract_revenue:
        Подтверждённая выручка по контракту.
        None означает, что значение неизвестно.

    items:
        Список позиций. Каждая позиция содержит:
        name             — название товара;
        quantity         — количество;
        unit_price       — цена за единицу;
        price_verified   — подтверждена ли цена поставщика.

    additional_costs:
        Подтверждённые дополнительные расходы.
        None означает, что расходы ещё не определены.

    Если хотя бы один обязательный финансовый показатель
    неизвестен или цена не подтверждена, прибыль и маржа
    не рассчитываются.
    """

    if not isinstance(items, list) or not items:
        raise ValueError("Необходимо передать список товаров")

    if additional_costs is not None:
        additional_costs = _validate_non_negative(
            additional_costs,
            "additional_costs",
        )

    if contract_revenue is not None:
        contract_revenue = _validate_non_negative(
            contract_revenue,
            "contract_revenue",
        )

    known_purchase_cost = Decimal("0")
    missing_data = []
    processed_items = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"Позиция {index + 1} должна быть словарём"
            )

        allowed_fields = {
            "name",
            "quantity",
            "unit_price",
            "price_verified",
        }

        unknown_fields = set(item) - allowed_fields

        if unknown_fields:
            raise ValueError(
                f"Неизвестные поля позиции {index + 1}: "
                f"{', '.join(sorted(unknown_fields))}"
            )

        name = item.get("name") or f"Позиция {index + 1}"
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")
        price_verified = item.get("price_verified")

        if quantity is None:
            missing_data.append(f"{name}: неизвестно количество")
            processed_items.append({
                "name": name,
                "status": "incomplete",
                "total": None,
            })
            continue

        quantity = _validate_non_negative(
            quantity,
            f"{name}.quantity",
        )

        if unit_price is None:
            missing_data.append(f"{name}: неизвестна цена")
            processed_items.append({
                "name": name,
                "status": "incomplete",
                "total": None,
            })
            continue

        unit_price = _validate_non_negative(
            unit_price,
            f"{name}.unit_price",
        )

        if not isinstance(price_verified, bool):
            raise ValueError(
                f"{name}: price_verified должен быть True или False"
            )

        if not price_verified:
            missing_data.append(
                f"{name}: цена поставщика не подтверждена"
            )
            processed_items.append({
                "name": name,
                "status": "unverified",
                "total": None,
            })
            continue

        item_total = quantity * unit_price
        known_purchase_cost += item_total

        processed_items.append({
            "name": name,
            "status": "confirmed",
            "total": item_total,
        })

    if contract_revenue is None:
        missing_data.append("Не определена выручка по контракту")

    if additional_costs is None:
        missing_data.append("Не определены дополнительные расходы")

    all_items_confirmed = all(
        item["status"] == "confirmed"
        for item in processed_items
    )

    complete = (
        all_items_confirmed
        and contract_revenue is not None
        and additional_costs is not None
    )

    total_purchase_cost = (
        known_purchase_cost if all_items_confirmed else None
    )

    gross_profit = None
    gross_margin_percent = None

    if complete:
        gross_profit = (
            contract_revenue
            - total_purchase_cost
            - additional_costs
        )

        if contract_revenue > 0:
            gross_margin_percent = (
                gross_profit / contract_revenue * Decimal("100")
            )

    return {
        "calculation_status": (
            "complete" if complete else "incomplete"
        ),
        "data_completeness": (
            "Полные данные" if complete else "Неполные данные"
        ),
        "contract_revenue": contract_revenue,
        "known_purchase_cost": known_purchase_cost,
        "total_purchase_cost": total_purchase_cost,
        "additional_costs": additional_costs,
        "gross_profit": gross_profit,
        "gross_margin_percent": gross_margin_percent,
        "missing_data": missing_data,
        "items": processed_items,
    }
