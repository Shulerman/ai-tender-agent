import re


def normalize_text(text: str) -> str:
    """
    Нормализует пробелы и переносы строк,
    не изменяя содержание текста.
    """
    return re.sub(r"\s+", " ", text).strip()


def validate_quotes(quotes: list[str], document_text: str) -> dict:
    """
    Проверяет, присутствует ли каждая цитата
    в исходном тексте документа.

    Возвращает:
    - accepted: подтверждённые цитаты;
    - rejected: неподтверждённые цитаты;
    - is_valid: все ли цитаты подтверждены.
    """

    normalized_document = normalize_text(document_text)

    accepted = []
    rejected = []

    for quote in quotes:
        if not isinstance(quote, str) or not quote.strip():
            rejected.append(quote)
            continue

        normalized_quote = normalize_text(quote)

        if normalized_quote and normalized_quote in normalized_document:
            accepted.append(quote)
        else:
            rejected.append(quote)

    return {
        "accepted": accepted,
        "rejected": rejected,
        "is_valid": len(rejected) == 0,
    }
