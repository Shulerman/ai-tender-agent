import re
from decimal import Decimal, InvalidOperation

from app.ai.technical_models import ProductAnalysis, NOT_SPECIFIED
from app.commercial.unit_normalizer import get_unit_definition


RANGE_PATTERN = re.compile(
    r"\d\s*(?:-|–|—|до|по)\s*\d",
    re.IGNORECASE,
)

QUALIFIER_PATTERN = re.compile(
    r"\b(?:не\s+менее|не\s+более|не\s+превышает|"
    r"не\s+меньше|не\s+выше|от|до|свыше|более|"
    r"минимум|максимум|около|примерно|порядка)\b",
    re.IGNORECASE,
)

MISSING_VALUES = {
    "",
    NOT_SPECIFIED.lower(),
    "не определено",
    "неизвестно",
    "по заявкам",
    "по потребности",
    "по мере необходимости",
}


def _result(product, estimated_quantity, status, reason):
    """Формирует результат, сохраняя исходные значения."""

    return {
        "name": product.name,
        "source_quantity": product.quantity,
        "source_unit": product.unit,
        "estimated_quantity": estimated_quantity,
        "parse_status": status,
        "parse_reason": reason,
    }


def parse_product_quantity(product: ProductAnalysis) -> dict:
    """
    Распознаёт однозначное числовое количество товара.

    Не преобразует диапазоны, ограничения и приблизительные значения
    в одно число. Исходные quantity и unit не изменяются.
    """

    if not isinstance(product, ProductAnalysis):
        raise TypeError("Ожидается объект ProductAnalysis")

    if not isinstance(product.quantity, str):
        return _result(
            product, None, "ambiguous",
            "Количество должно быть строкой",
        )

    source = product.quantity.strip()

    if source.lower() in MISSING_VALUES:
        return _result(
            product, None, "missing",
            "Количество в документе не указано",
        )

    if RANGE_PATTERN.search(source):
        return _result(
            product, None, "ambiguous",
            "Указан диапазон количества",
        )

    if QUALIFIER_PATTERN.search(source):
        return _result(
            product, None, "ambiguous",
            "Количество содержит ограничение или приблизительную оценку",
        )

    # Отделяем числовую часть от необязательной единицы измерения.
    match = re.fullmatch(
        r"([\d\s\u00a0\u202f]+(?:[.,]\d+)?)\s*(.*?)",
        source,
    )

    if not match:
        return _result(
            product, None, "ambiguous",
            "Не удалось однозначно распознать числовое количество",
        )

    numeric_text = match.group(1).strip()
    suffix_unit = match.group(2).strip()

    if suffix_unit:
        source_definition = get_unit_definition(suffix_unit)
        target_definition = get_unit_definition(product.unit)

        if source_definition and target_definition:
            units_match = source_definition == target_definition
        else:
            normalize_name = lambda value: (
                "".join(value.lower().split()).rstrip(".")
            )
            units_match = (
                isinstance(product.unit, str)
                and normalize_name(suffix_unit)
                == normalize_name(product.unit)
            )

        if not units_match:
            return _result(
                product, None, "ambiguous",
                "Единица измерения в quantity не совпадает с полем unit",
            )

    # Пробелы и неразрывные пробелы между разрядами допустимы.
    normalized = (
        numeric_text.replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
    )

    # Точка или запятая с тремя цифрами справа неоднозначна.
    if re.fullmatch(r"\d{1,3}[.,]\d{3}", normalized):
        return _result(
            product, None, "ambiguous",
            "Неоднозначный разделитель разрядов и дробной части",
        )

    if not re.fullmatch(r"\d+(?:[.,]\d+)?", normalized):
        return _result(
            product, None, "ambiguous",
            "Не удалось однозначно распознать числовое количество",
        )

    try:
        quantity = Decimal(normalized.replace(",", "."))
    except InvalidOperation:
        return _result(
            product, None, "ambiguous",
            "Некорректное числовое значение",
        )

    if not quantity.is_finite() or quantity <= 0:
        return _result(
            product, None, "ambiguous",
            "Количество должно быть конечным числом больше нуля",
        )

    return _result(
        product, quantity, "parsed",
        "Количество однозначно распознано",
    )