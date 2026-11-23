from pathlib import Path

path = Path("tests/test_commercial_import_api.py")
content = path.read_text(encoding="utf-8")

old_import = """from app.commercial.models import (
    SupplierDB,
    ProductDB,
    PriceListImportRowDB,
    SupplierOfferDB,
)"""

new_import = """from app.commercial.models import (
    SupplierDB,
    ProductDB,
    ManufacturerDB,
    PriceListImportRowDB,
    SupplierOfferDB,
)"""

if "    ManufacturerDB," not in content:
    if old_import not in content:
        raise SystemExit("ОШИБКА: блок импорта моделей не найден")
    content = content.replace(old_import, new_import, 1)

tests = '''

def test_search_products_api_returns_manufacturer_and_product_details(client, db):
    token = uuid.uuid4().hex

    manufacturer = ManufacturerDB(
        name=f"Производитель {token}",
        country="Россия",
    )
    db.add(manufacturer)
    db.flush()

    product_with_manufacturer = ProductDB(
        name=f"Товар с производителем {token}",
        article_number=f"WITH-{token}",
        manufacturer_id=manufacturer.id,
        unit="шт.",
        category="Оборудование",
        created_at=datetime.now(),
    )

    product_without_manufacturer = ProductDB(
        name=f"Товар без производителя {token}",
        article_number=f"WITHOUT-{token}",
        unit="кг",
        category="Материалы",
        created_at=datetime.now(),
    )

    db.add_all([
        product_with_manufacturer,
        product_without_manufacturer,
    ])
    db.commit()

    response = client.get(
        "/commercial/products/search",
        params={"q": token},
    )

    assert response.status_code == 200

    results = {
        item["id"]: item
        for item in response.json()["products"]
    }

    with_manufacturer = results[product_with_manufacturer.id]
    without_manufacturer = results[product_without_manufacturer.id]

    assert with_manufacturer["manufacturer"] == manufacturer.name
    assert with_manufacturer["manufacturer_country"] == "Россия"
    assert with_manufacturer["unit"] == "шт."
    assert with_manufacturer["category"] == "Оборудование"

    assert without_manufacturer["manufacturer"] is None
    assert without_manufacturer["manufacturer_country"] is None
    assert without_manufacturer["unit"] == "кг"
    assert without_manufacturer["category"] == "Материалы"


def test_search_products_api_rejects_query_longer_than_500_characters(client):
    response = client.get(
        "/commercial/products/search",
        params={"q": "x" * 501},
    )

    assert response.status_code == 422
'''

if "def test_search_products_api_returns_manufacturer_and_product_details" not in content:
    content = content.rstrip() + "\n" + tests + "\n"

path.write_text(content, encoding="utf-8", newline="\n")

saved = path.read_text(encoding="utf-8")

checks = [
    "    ManufacturerDB,",
    "def test_search_products_api_returns_manufacturer_and_product_details",
    "def test_search_products_api_rejects_query_longer_than_500_characters",
    'manufacturer_country"] == "Россия"',
    'params={"q": "x" * 501}',
]

for item in checks:
    if item not in saved:
        raise SystemExit("ОШИБКА проверки после записи: " + item)

print("SUCCESS: импорты и два API-теста записаны и проверены.")
