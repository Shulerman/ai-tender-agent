from pathlib import Path

path = Path("app/main.py")
content = path.read_text(encoding="utf-8")

start_marker = '@app.get("/commercial/products/search")'
end_marker = '@app.get("/commercial/imports/{import_id}/unmatched")'

assert content.count(start_marker) == 1, "Не найден уникальный endpoint поиска"
assert content.count(end_marker) == 1, "Не найден следующий endpoint"

old_import = """from app.commercial.models import (
    SupplierDB,
    ProductDB,
    PriceListImportDB,
    PriceListImportRowDB,
)"""

new_import = """from app.commercial.models import (
    SupplierDB,
    ProductDB,
    ManufacturerDB,
    PriceListImportDB,
    PriceListImportRowDB,
)"""

assert old_import in content, "Не найден исходный блок импорта"

new_function = '''@app.get("/commercial/products/search")
def search_commercial_products(
    q: str,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Ищет товары каталога по названию и артикулу."""

    search_term = q.strip().casefold()

    if not search_term:
        raise HTTPException(
            status_code=422,
            detail="Поисковый запрос не может быть пустым",
        )

    if len(search_term) > 500:
        raise HTTPException(
            status_code=422,
            detail="Поисковый запрос не должен превышать 500 символов",
        )

    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=422,
            detail="limit должен быть от 1 до 50",
        )

    products = (
        db.query(ProductDB, ManufacturerDB)
        .outerjoin(
            ManufacturerDB,
            ProductDB.manufacturer_id == ManufacturerDB.id,
        )
        .order_by(ProductDB.id.asc())
        .all()
    )

    exact_matches = []
    partial_matches = []

    for product, manufacturer in products:
        name = (product.name or "").casefold()
        article = (product.article_number or "").casefold()

        if search_term == name or search_term == article:
            exact_matches.append((product, manufacturer))
        elif search_term in name or search_term in article:
            partial_matches.append((product, manufacturer))

    matches = (exact_matches + partial_matches)[:limit]

    return {
        "query": q.strip(),
        "count": len(matches),
        "limit": limit,
        "products": [
            {
                "id": product.id,
                "name": product.name,
                "article_number": product.article_number,
                "manufacturer": manufacturer.name if manufacturer else None,
                "manufacturer_country": manufacturer.country if manufacturer else None,
                "unit": product.unit,
                "category": product.category,
            }
            for product, manufacturer in matches
        ],
    }
'''

content = content.replace(old_import, new_import, 1)
start = content.index(start_marker)
end = content.index(end_marker, start)
content = content[:start] + new_function + "\n\n" + content[end:]

path.write_text(content, encoding="utf-8", newline="\n")

saved = path.read_text(encoding="utf-8")
required = [
    "ManufacturerDB",
    "if len(search_term) > 500:",
    ".outerjoin(",
    '"manufacturer_country": manufacturer.country if manufacturer else None,',
    '"unit": product.unit,',
    '"category": product.category,',
]

for item in required:
    assert item in saved, f"Проверка не пройдена: {item}"

print("SUCCESS: endpoint и импорт записаны и проверены.")
