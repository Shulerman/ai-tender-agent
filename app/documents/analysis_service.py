from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.evidence_validator import normalize_text
from app.ai.technical_analyst import analyze_technical_requirements
from app.documents.models import (
    DocumentChunkDB,
    TenderAnalysisDB,
    TenderDocumentDB,
    TenderRequirementDB,
)


def _find_source_chunk(
    quote: str,
    chunks: list[DocumentChunkDB],
) -> DocumentChunkDB | None:
    """Находит фрагмент, в котором дословно присутствует цитата."""

    if not isinstance(quote, str) or not quote.strip():
        return None

    normalized_quote = normalize_text(quote)

    matching_chunks = [
        chunk
        for chunk in chunks
        if normalized_quote in normalize_text(chunk.text)
    ]

    if len(matching_chunks) == 1:
        return matching_chunks[0]

    return None


def _extract_quotes(item: dict) -> list[str]:
    """Возвращает уникальные цитаты, начиная с evidence."""

    quotes = []

    for evidence in item.get("evidence", []):
        if isinstance(evidence, dict):
            quote = evidence.get("quote")
            if isinstance(quote, str) and quote.strip():
                quotes.append(quote)

    quotes.extend(
        quote
        for quote in item.get("quotes", [])
        if isinstance(quote, str) and quote.strip()
    )

    return list(dict.fromkeys(quotes))


def _build_requirement_text(
    requirement_type: str,
    item: dict,
) -> str:
    """Формирует краткое текстовое представление требования."""

    if requirement_type == "product":
        return item["name"].strip()

    if requirement_type == "delivery":
        parts = []

        delivery_time = item.get("delivery_time")
        delivery_address = item.get("delivery_address")

        if delivery_time and delivery_time != "Не указано":
            parts.append(f"Срок поставки: {delivery_time}")

        if delivery_address and delivery_address != "Не указано":
            parts.append(f"Адрес поставки: {delivery_address}")

        return "; ".join(parts) or "Условия поставки"

    if requirement_type == "document":
        return item["requirement_type"].strip()

    if requirement_type == "risk":
        return item["description"].strip()

    raise ValueError(
        f"Неизвестный тип требования: {requirement_type}"
    )


def _build_requirement_records(
    analysis_result: dict,
    chunks: list[DocumentChunkDB],
    analysis_id: int,
    document_id: int,
) -> list[TenderRequirementDB]:
    """Преобразует результат технического анализа в записи БД."""

    sections = (
        ("product", "products"),
        ("delivery", "delivery_requirements"),
        ("document", "document_requirements"),
        ("risk", "risks_and_uncertainties"),
    )

    records = []

    for requirement_type, section_name in sections:
        items = analysis_result.get(section_name, [])

        if not isinstance(items, list):
            raise ValueError(
                f"Некорректный раздел анализа: {section_name}"
            )

        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"Некорректная запись в разделе {section_name}"
                )

            requirement_text = _build_requirement_text(
                requirement_type,
                item,
            )

            if not requirement_text:
                raise ValueError(
                    f"Пустое требование в разделе {section_name}"
                )

            source_chunk = None
            evidence_quote = None

            for quote in _extract_quotes(item):
                source_chunk = _find_source_chunk(quote, chunks)

                if source_chunk is not None:
                    evidence_quote = quote
                    break

            records.append(
                TenderRequirementDB(
                    document_id=document_id,
                    analysis_id=analysis_id,
                    source_chunk_id=(
                        source_chunk.id if source_chunk else None
                    ),
                    requirement_type=requirement_type,
                    requirement_text=requirement_text,
                    attributes=item,
                    evidence_quote=evidence_quote,
                    confidence=None,
                    extraction_status=(
                        "Источник найден"
                        if source_chunk is not None
                        else "Требует проверки"
                    ),
                )
            )

    return records


async def analyze_and_save_document_requirements(
    db: Session,
    document_id: int,
) -> dict:
    """
    Анализирует сохранённые фрагменты документа
    и сохраняет структурированные требования.

    Каждый запуск создаёт отдельную запись анализа.
    Предыдущие результаты не удаляются.
    """

    document = db.get(TenderDocumentDB, document_id)

    if document is None:
        raise ValueError("Документ не найден")

    chunks = (
        db.query(DocumentChunkDB)
        .filter(DocumentChunkDB.document_id == document_id)
        .order_by(DocumentChunkDB.sequence_number)
        .all()
    )

    if not chunks:
        raise ValueError("У документа нет текстовых фрагментов")

    document_text = "\n\n".join(chunk.text for chunk in chunks)

    if not document_text.strip():
        raise ValueError("Текст документа пуст")

    analysis = TenderAnalysisDB(
        document_id=document_id,
        analysis_type="technical_requirements",
        status="Выполняется",
    )

    try:
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

    except Exception:
        db.rollback()
        raise

    analysis_id = analysis.id

    try:
        result = await analyze_technical_requirements(document_text)

        if not isinstance(result, dict):
            raise ValueError(
                "Анализатор вернул результат неправильного типа"
            )

        records = _build_requirement_records(
            analysis_result=result,
            chunks=chunks,
            analysis_id=analysis_id,
            document_id=document_id,
        )

        db.add_all(records)

        analysis.result_json = result
        analysis.status = "Завершён"
        analysis.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.commit()
        db.refresh(analysis)

        return {
            "analysis_id": analysis.id,
            "document_id": document_id,
            "status": analysis.status,
            "requirements_count": len(records),
            "requirements_with_source": sum(
                record.source_chunk_id is not None
                for record in records
            ),
            "result": result,
        }

    except Exception as error:
        db.rollback()

        failed_analysis = db.get(TenderAnalysisDB, analysis_id)

        if failed_analysis is not None:
            failed_analysis.status = "Ошибка"
            failed_analysis.error = str(error)
            failed_analysis.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()

        raise
