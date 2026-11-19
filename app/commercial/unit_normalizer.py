from decimal import Decimal, InvalidOperation


UNIT_DEFINITIONS = {
    # Масса: базовая единица — кг.
    "mg": ("mass", Decimal("0.000001"), "кг"),
    "мг": ("mass", Decimal("0.000001"), "кг"),
    "g": ("mass", Decimal("0.001"), "кг"),
    "гр": ("mass", Decimal("0.001"), "кг"),
    "г": ("mass", Decimal("0.001"), "кг"),
    "kg": ("mass", Decimal("1"), "кг"),
    "кг": ("mass", Decimal("1"), "кг"),
    "t": ("mass", Decimal("1000"), "кг"),
    "т": ("mass", Decimal("1000"), "кг"),

    # Объём: базовая единица — литр.
    "ml": ("volume", Decimal("0.001"), "л"),
    "мл": ("volume", Decimal("0.001"), "л"),
    "l": ("volume", Decimal("1"), "л"),
    "л": ("volume", Decimal("1"), "л"),
    "m3": ("volume", Decimal("1000"), "л"),
    "м3": ("volume", Decimal("1000"), "л"),
    "м³": ("volume", Decimal("1000"), "л"),

    # Длина: базовая единица — метр.
    "mm": ("length", Decimal("0.001"), "м"),
    "мм": ("length", Decimal("0.001"), "м"),
    "cm": ("length", Decimal("0.01"), "м"),
    "см": ("length", Decimal("0.01"), "м"),
    "m": ("length", Decimal("1"), "м"),
    "м": ("length", Decimal("1"), "м"),
    "km": ("length", Decimal("1000"), "м"),
    "км": ("length", Decimal("1000"), "м"),

    # Площадь: базовая единица — м².
    "cm2": ("area", Decimal("0.0001"), "м²"),
    "см2": ("area", Decimal("0.0001"), "м²"),
    "см²": ("area", Decimal("0.0001"), "м²"),
    "m2": ("area", Decimal("1"), "м²"),
    "м2": ("area", Decimal("1"), "м²"),
    "м²": ("area", Decimal("1"), "м²"),

    # Количество: базовая единица — штука.
    "шт": ("quantity", Decimal("1"), "шт."),
    "шт.": ("quantity", Decimal("1"), "шт."),
    "штука": ("quantity", Decimal("1"), "шт."),
    "штуки": ("quantity", Decimal("1"), "шт."),
    "штук": ("quantity", Decimal("1"), "шт."),
    "ед": ("quantity", Decimal("1"), "шт."),
    "ед.": ("quantity", Decimal("1"), "шт."),
    "единица": ("quantity", Decimal("1"), "шт."),
    "единицы": ("quantity", Decimal("1"), "шт."),
    "единиц": ("quantity", Decimal("1"), "шт."),
}


def _normalize_unit_name(unit: str) -> str:
    """Нормализует написание единицы измерения."""

    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("Единица измерения не указана")

    return " ".join(unit.lower().strip().split())


def get_unit_definition(unit: str):
    """Возвращает семейство, коэффициент и базовую единицу."""

    normalized = _normalize_unit_name(unit)
    return UNIT_DEFINITIONS.get(normalized)


def normalize_unit_price(
    price,
    source_unit: str,
    target_unit: str,
    db=None,
    product_id: int = None,
    supplier_id: int = None,
):
    """
    Пересчитывает цену за исходную единицу в цену за целевую единицу.

    Для стандартных единиц используются физические коэффициенты.
    Для нестандартных упаковок используется коэффициент из БД.
    """

    try:
        source_price = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Некорректная цена")

    if not source_price.is_finite() or source_price < 0:
        raise ValueError("Цена должна быть конечным неотрицательным числом")

    source_name = _normalize_unit_name(source_unit)
    target_name = _normalize_unit_name(target_unit)

    source_definition = get_unit_definition(source_name)
    target_definition = get_unit_definition(target_name)

    if source_definition and target_definition:
        source_family, source_factor, _ = source_definition
        target_family, target_factor, _ = target_definition

        if source_family != target_family:
            raise ValueError(
                "Нельзя пересчитывать единицы разных физических категорий"
            )

        # Цена за одну исходную единицу / количество целевых единиц
        # в одной исходной единице.
        return source_price * target_factor / source_factor

    if source_name == target_name:
        return source_price

    if db is None or product_id is None:
        raise ValueError(
            "Для пересчёта нестандартных единиц требуется товар и база данных"
        )

    from app.commercial.service import get_product_unit_conversion

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
        raise ValueError("В базе найден некорректный коэффициент пересчёта")

    return source_price / factor
