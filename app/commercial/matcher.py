"""Детерминированное сопоставление требований тендера с товарами каталога."""

import re
from decimal import Decimal, InvalidOperation


ALGORITHM_VERSION = "1.0"


def _normalize_name(value):
    """Нормализует название характеристики для поиска."""
    return re.sub(r"[^a-zа-яё0-9]", "", str(value).casefold())


def _normalize_unit(value):
    if value is None:
        return None
    return str(value).strip().casefold()


def _as_decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        normalized = str(value).strip().replace(",", ".")
        return Decimal(normalized)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _product_attribute_value(value):
    """Извлекает значение и единицу измерения из атрибута каталога."""
    if isinstance(value, dict):
        return value.get("value"), value.get("unit")
    return value, None


def _compare_values(required, actual, operator=None):
    """Возвращает True при подтверждённом соответствии, False при отличии, None при неопределённости."""
    required_unit = _normalize_unit(required.get("unit"))
    actual_value, actual_unit = _product_attribute_value(actual)
    actual_unit = _normalize_unit(actual_unit)

    if required_unit != actual_unit:
        return None

    expected_value = required.get("value")
    expected_number = _as_decimal(expected_value)
    actual_number = _as_decimal(actual_value)

    if expected_number is not None and actual_number is not None:
        operation = (operator or "=").strip().casefold()
        comparisons = {
            "=": actual_number == expected_number,
            "==": actual_number == expected_number,
            ">": actual_number > expected_number,
            ">=": actual_number >= expected_number,
            "<": actual_number < expected_number,
            "<=": actual_number <= expected_number,
        }
        return comparisons.get(operation)

    if operator not in (None, "", "=", "=="):
        return None

    if expected_value is None or actual_value is None:
        return None

    return str(expected_value).strip().casefold() == str(actual_value).strip().casefold()


def compare_product_to_requirement(requirement_attributes, product_attributes):
    """
    Сравнивает структурированные характеристики требования с характеристиками товара.

    Не выполняет неявную конвертацию единиц измерения.
    Неизвестные характеристики не считаются совпадающими.
    """
    if not isinstance(requirement_attributes, list):
        requirement_attributes = []

    if not isinstance(product_attributes, dict):
        product_attributes = {}

    product_index = {
        _normalize_name(name): value
        for name, value in product_attributes.items()
    }

    confirmed = []
    missing = []
    discrepancies = []

    required_attributes = [
        item for item in requirement_attributes
        if isinstance(item, dict) and item.get("is_required") is not False
    ]

    for item in required_attributes:
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        key = _normalize_name(name)
        product_value = product_index.get(key)

        if product_value is None:
            missing.append({
                "name": name,
                "required_value": item.get("value"),
                "unit": item.get("unit"),
                "reason": "Характеристика отсутствует в каталоге",
            })
            continue

        result = _compare_values(
            item,
            product_value,
            item.get("operator"),
        )

        actual_value, actual_unit = _product_attribute_value(product_value)

        if result is True:
            confirmed.append({
                "name": name,
                "required_value": item.get("value"),
                "actual_value": actual_value,
                "unit": item.get("unit"),
            })
        elif result is False:
            discrepancies.append({
                "name": name,
                "required_value": item.get("value"),
                "actual_value": actual_value,
                "required_unit": item.get("unit"),
                "actual_unit": actual_unit,
                "reason": "Значение характеристики отличается",
            })
        else:
            missing.append({
                "name": name,
                "required_value": item.get("value"),
                "actual_value": actual_value,
                "unit": item.get("unit"),
                "reason": "Недостаточно данных для проверки или единицы измерения не совпадают",
            })

    total = len(required_attributes)
    confirmed_count = len(confirmed)

    if total == 0 or confirmed_count == 0:
        status = "Недостаточно данных"
    elif confirmed_count == total and not missing and not discrepancies:
        status = "Полное соответствие"
    else:
        status = "Потенциальный аналог"

    score = (
        round(confirmed_count / total * 100, 2)
        if total
        else None
    )

    return {
        "match_status": status,
        "match_score": score,
        "confirmed_characteristics": confirmed,
        "missing_characteristics": missing,
        "discrepancies": discrepancies,
        "is_candidate": confirmed_count > 0,
        "algorithm_version": ALGORITHM_VERSION,
    }
