from app.ai.technical_analyst import analyze_technical_requirements
from app.ai.legal_analyst import analyze_legal_requirements


async def analyze_full_tender(document_text: str) -> dict:
    """
    Выполняет полный технический и юридический анализ закупки.
    Оба аналитических модуля получают один исходный текст.
    """

    if not isinstance(document_text, str) or not document_text.strip():
        raise ValueError("Текст документа пуст")

    technical_analysis = await analyze_technical_requirements(
        document_text
    )

    legal_analysis = await analyze_legal_requirements(
        document_text
    )

    return {
        "status": "success",
        "document_text_length": len(document_text),
        "technical_analysis": technical_analysis,
        "legal_analysis": legal_analysis,
    }
