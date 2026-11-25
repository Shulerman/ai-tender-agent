"""Детерминированное сопоставление требований тендера с товарами каталога."""

import re
from decimal import Decimal, InvalidOperation

from app.commercial.unit_normalizer import get_unit_definition


ALGORITHM_VERSION = "1.1"


_NAME_ALIASES = {
    # Диаметр без уточнения типа.
    "diameter": "diameter",
    "диаметр": "diameter",
    "ø": "diameter",
    "⌀": "diameter",

    # Наружный и внутренний диаметры остаются разными характеристиками.
    "outerdiameter": "outerdiameter",
    "наружныйдиаметр": "outerdiameter",
    "внешнийдиаметр": "outerdiameter",
    "innerdiameter": "innerdiameter",
    "внутреннийдиаметр": "innerdiameter",

    "length": "length",
    "длина": "length",
    "width": "width",
    "ширина": "width",
    "height": "height",
    "высота": "height",
    "thickness": "thickness",
    "толщина": "thickness",
    "wallthickness": "wallthickness",
    "толщинастенки": "wallthickness",
}


def _normalize_name(value):
    """Нормализует название характеристики с учётом явных синонимов."""
    raw = str(value).casefold().strip()

    if raw in ("ø", "⌀"):
        return "diameter"

    compact = re.sub(r"[^a-zа-яё0-9]", "", raw)
    return _NAME_ALIASES.get(compact, compact)


def _normalize_unit(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    normalized = value.strip().casefold()
    return normalized or None


def _as_decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        normalized = str(value).strip().replace(",", ".")
        number = Decimal(normalized)
        return number if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_non_finite_decimal(value):
    if isinstance(value, bool) or value is None:
        return False
    try:
        normalized = str(value).strip().replace(",", ".")
        return not Decimal(normalized).is_finite()
    except (InvalidOperation, TypeError, ValueError):
        return False


def _product_attribute_value(value):
    """Извлекает значение и единицу измерения из атрибута каталога."""
    if isinstance(value, dict):
        return value.get("value"), value.get("unit")
    return value, None


def _compare_values(required, actual, operator=None):
    """Возвращает True при подтверждённом соответствии, False при отличии, None при неопределённости."""
    required_unit_value = required.get("unit")
    actual_value, actual_unit_value = _product_attribute_value(actual)

    if (
        required_unit_value is not None
        and not isinstance(required_unit_value, str)
    ) or (
        actual_unit_value is not None
        and not isinstance(actual_unit_value, str)
    ):
        return None

    required_unit = _normalize_unit(required_unit_value)
    actual_unit = _normalize_unit(actual_unit_value)
    unit_conversion_factor = None

    if required_unit != actual_unit:
        if required_unit is None or actual_unit is None:
            return None

        required_definition = get_unit_definition(required_unit)
        actual_definition = get_unit_definition(actual_unit)

        if (
            required_definition is None
            or actual_definition is None
            or required_definition[0] != actual_definition[0]
        ):
            return None

        # Приводим фактическое значение к единице требования.
        unit_conversion_factor = (
            actual_definition[1] / required_definition[1]
        )

    expected_value = required.get("value")

    # Пустые значения не являются подтверждением характеристики.
    if (
        expected_value is None
        or actual_value is None
        or (
            isinstance(expected_value, str)
            and not expected_value.strip()
        )
        or (
            isinstance(actual_value, str)
            and not actual_value.strip()
        )
    ):
        return None

    if (
        _is_non_finite_decimal(expected_value)
        or _is_non_finite_decimal(actual_value)
    ):
        return None

    if operator is not None and not isinstance(operator, str):
        return None

    operation = (operator or "=").strip().casefold()
    allowed_operators = {"=", "==", ">", ">=", "<", "<="}
    if operation not in allowed_operators:
        return None

    expected_number = _as_decimal(expected_value)
    actual_number = _as_decimal(actual_value)

    if unit_conversion_factor is not None:
        if expected_number is None or actual_number is None:
            return None
        actual_number *= unit_conversion_factor

    if expected_number is not None and actual_number is not None:
        comparisons = {
            "=": actual_number == expected_number,
            "==": actual_number == expected_number,
            ">": actual_number > expected_number,
            ">=": actual_number >= expected_number,
            "<": actual_number < expected_number,
            "<=": actual_number <= expected_number,
        }
        return comparisons[operation]

    if operation not in ("=", "=="):
        return None

    # Числовые строки с неоднозначными разделителями нельзя
    # подтверждать простым текстовым сравнением.
    numeric_pattern = re.compile(r"^[+-]?[0-9][0-9.,\s]*$")
    if (
        expected_number is None
        and isinstance(expected_value, str)
        and numeric_pattern.fullmatch(expected_value.strip())
    ) or (
        actual_number is None
        and isinstance(actual_value, str)
        and numeric_pattern.fullmatch(actual_value.strip())
    ):
        return None

    # Булевы значения сравниваются только с булевыми значениями.
    if isinstance(expected_value, bool) or isinstance(actual_value, bool):
        if (
            isinstance(expected_value, bool)
            and isinstance(actual_value, bool)
            and operation in ("=", "==")
        ):
            return expected_value == actual_value
        return None

    # Текстовый fallback допустим только для двух строк.
    # Списки, словари и прочие типы не подтверждают соответствие
    # через совпадение их строкового представления.
    if not isinstance(expected_value, str) or not isinstance(actual_value, str):
        return None

    return expected_value.strip().casefold() == actual_value.strip().casefold()


def compare_product_to_requirement(requirement_attributes, product_attributes):
    """
    Сравнивает структурированные характеристики требования с характеристиками товара.

    Конвертирует известные стандартные единицы только внутри одной физической группы.
    Неизвестные единицы и характеристики не считаются подтверждённым совпадением.
    """
    if not isinstance(requirement_attributes, list):
        requirement_attributes = []

    if not isinstance(product_attributes, dict):
        product_attributes = {}

    product_index = {}
    ambiguous_product_keys = set()

    for name, value in product_attributes.items():
        key = _normalize_name(name)
        if not key:
            continue
        if key in product_index:
            ambiguous_product_keys.add(key)
        else:
            product_index[key] = value

    confirmed = []
    missing = []
    discrepancies = []

    required_attributes = [
        item for item in requirement_attributes
        if (
            isinstance(item, dict)
            and item.get("is_required") is not False
            and isinstance(item.get("name"), str)
            and item["name"].strip()
            and _normalize_name(item["name"])
        )
    ]

    for item in required_attributes:
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        key = _normalize_name(name)

        if key in ambiguous_product_keys:
            missing.append({
                "name": name,
                "required_value": item.get("value"),
                "unit": item.get("unit"),
                "reason": "В каталоге обнаружены неоднозначные названия характеристики",
            })
            continue

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
