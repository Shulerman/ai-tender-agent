from app.database import SessionLocal
from app.legal_knowledge.service import get_legal_provision

db = SessionLocal()

try:
    result = get_legal_provision(
        db=db,
        version_id="44-FZ-2026-10-01",
        article_number="1",
    )

    assert result is not None, "Статья 1 не найдена."

    assert result["article_number"] == "1"
    assert result["text"].strip(), "Текст статьи пуст."

    print("Статья найдена!")
    print("Номер:", result["article_number"])
    print("Заголовок:", result["title"])
    print("Длина текста:", len(result["text"]))
    print("\nТЕСТ ПОИСКА СТАТЬИ ПРОЙДЕН")

finally:
    db.close()
