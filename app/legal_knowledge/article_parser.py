
import re
from uuid import NAMESPACE_URL, uuid5


ARTICLE_PATTERN = re.compile(
    r"^[ \t]*Статья\s+(\d+(?:\.\d+)*)\.\s*(.*?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

CHAPTER_PATTERN = re.compile(
    r"^[ \t]*Глава\s+(\d+(?:\.\d+)*)\.\s*(.*?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def split_into_articles(document_text: str) -> list[dict]:
    """
    Разделяет текст нормативного акта на отдельные статьи.
    Сохраняет номер статьи, заголовок, главу и полный текст.
    """

    if not isinstance(document_text, str) or not document_text.strip():
        raise ValueError("Текст документа пуст")

    article_matches = list(ARTICLE_PATTERN.finditer(document_text))
    chapter_matches = list(CHAPTER_PATTERN.finditer(document_text))

    if not article_matches:
        raise ValueError("В документе не найдены статьи")

    articles = []
    chapter_index = 0
    current_chapter = None

    for index, match in enumerate(article_matches):
        while (
            chapter_index < len(chapter_matches)
            and chapter_matches[chapter_index].start() < match.start()
        ):
            chapter_match = chapter_matches[chapter_index]

            current_chapter = {
                "number": chapter_match.group(1),
                "title": chapter_match.group(2).strip(),
            }

            chapter_index += 1

        start = match.start()

        if index + 1 < len(article_matches):
            end = article_matches[index + 1].start()
        else:
            end = len(document_text)

        article_text = document_text[start:end].strip()

        articles.append({
            "article_number": match.group(1),
            "title": match.group(2).strip(),
            "chapter_number": (
                current_chapter["number"]
                if current_chapter else None
            ),
            "chapter_title": (
                current_chapter["title"]
                if current_chapter else None
            ),
            "text": article_text,
        })

    return articles


def build_legal_provisions(
    document_text: str,
    act_id: str,
    version_id: str,
) -> list[dict]:
    """
    Создаёт записи статей, связанные с конкретным актом и его редакцией.

    Идентификаторы статей стабильны:
    повторная обработка одной редакции не создаёт новые ID.
    """

    if not act_id or not version_id:
        raise ValueError(
            "Необходимо указать act_id и version_id"
        )

    articles = split_into_articles(document_text)
    provisions = []

    for article in articles:
        article_number = article["article_number"]

        unique_key = (
            f"ai-tender-agent:{act_id}:"
            f"{version_id}:{article_number}"
        )

        provisions.append({
            "provision_id": str(
                uuid5(NAMESPACE_URL, unique_key)
            ),
            "version_id": version_id,
            "article_number": article_number,
            "title": article["title"],
            "text": article["text"],
        })

    return provisions
