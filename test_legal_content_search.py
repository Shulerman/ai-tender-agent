from app.database import SessionLocal
from app.legal_knowledge.service import search_legal_provisions

db = SessionLocal()

try:
    results = search_legal_provisions(
        db=db,
        version_id="44-FZ-2026-10-01",
        search_text="обеспечение исполнения контракта",
        limit=10,
    )

    print("Найдено статей:", len(results))

    assert results, "Поиск не нашёл ни одной статьи."

    found = any(
        "обеспечение исполнения контракта" in
        (item.get("title", "") + " " + item.get("text", "")).casefold()
        for item in results
    )

    assert found, "Искомая фраза отсутствует в результатах."

    for item in results:
        print("\nСтатья:", item["article_number"])
        print("Заголовок:", item["title"])
        print(item["text"][:300])

    print("\nТЕСТ ПОИСКА ПО СОДЕРЖАНИЮ ПРОЙДЕН")

finally:
    db.close()
