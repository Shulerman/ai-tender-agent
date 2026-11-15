from app.ai.legal_analyst import (
    detect_procurement_law,
    find_relevant_legal_articles,
)


document_text = """
Закупка проводится в соответствии с Федеральным законом 44-ФЗ.
Поставка товара осуществляется в течение 10 рабочих дней
после заключения контракта.
Заказчик устанавливает обеспечение исполнения контракта.
Оплата производится после приемки товара.
"""

law = detect_procurement_law(document_text)
articles = find_relevant_legal_articles(document_text, law)

print("Определённый закон:", law)
print("Найдено статей:", len(articles))

assert law == "44-ФЗ", (
    f"Ожидался закон 44-ФЗ, получено: {law}"
)

assert articles, (
    "Контекстный анализ не нашёл ни одной статьи в тестовой базе."
)

article_numbers = {
    str(article["article_number"])
    for article in articles
}

assert "96" in article_numbers, (
    "Статья 96 не найдена, хотя документ содержит "
    "условие об обеспечении исполнения контракта."
)

for article in articles:
    print("\nСтатья:", article["article_number"])
    print("Название:", article["title"])
    print("Фрагмент текста:", article["text"][:500])

print("\nТЕСТ КОНТЕКСТНОГО ПОИСКА ПРОЙДЕН")
