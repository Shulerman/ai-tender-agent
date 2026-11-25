from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.evidence_validator import normalize_text
from app.ai.technical_analyst import analyze_technical_requirements
from app.ai.technical_models import TechnicalAnalysis
from app.ai.evidence_relevance_validator import validate_evidence_relevance
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

    if requirement_type == "technical":
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        value = str(item.get("value") or "").strip()
        operator = str(item.get("operator") or "").strip()
        unit = str(item.get("unit") or "").strip()

        if description:
            return f"{name}: {description}" if name else description

        value_parts = " ".join(
            part for part in (operator, value, unit) if part
        )
        return f"{name}: {value_parts}" if value_parts else name

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


def _semantic_evidence_status(item: dict) -> str:
    """Сводит семантические статусы, не смешивая их с поиском источника."""

    evidence_items = list(item.get("evidence") or [])
    for attribute in item.get("attributes") or []:
        if isinstance(attribute, dict):
            evidence_items.extend(attribute.get("evidence") or [])

    statuses = [
        evidence.get("relevance_status")
        for evidence in evidence_items
        if isinstance(evidence, dict)
    ]
    if not statuses:
        return "Не проверено"
    if "Противоречит" in statuses:
        return "Противоречит"
    if all(status == "Подтверждает" for status in statuses):
        return "Подтверждено"
    return "Не подтверждено"


def _build_requirement_records(
    analysis_result: dict,
    chunks: list[DocumentChunkDB],
    analysis_id: int,
    document_id: int,
) -> list[TenderRequirementDB]:
    """Преобразует результат технического анализа в записи БД."""

    sections = (
        ("product", "products"),
        ("technical", "technical_requirements"),
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
                    attributes={
                        **item,
                        "semantic_evidence_status": (
                            _semantic_evidence_status(item)
                        ),
                    },
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


def _flatten_requirement_items(result: dict) -> list[tuple[str, dict]]:
    """Возвращает требования в том же порядке, в котором они сохраняются в БД."""

    sections = (
        ("product", "products"),
        ("technical", "technical_requirements"),
        ("delivery", "delivery_requirements"),
        ("document", "document_requirements"),
        ("risk", "risks_and_uncertainties"),
    )
    flattened = []

    for requirement_type, section_name in sections:
        items = result.get(section_name, [])
        if not isinstance(items, list):
            raise ValueError(f"Некорректный раздел анализа: {section_name}")

        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"Некорректная запись в разделе {section_name}"
                )
            flattened.append((requirement_type, item))

    return flattened


def _walk_evidence(value):
    """Обходит evidence верхнего уровня и вложенные атрибуты."""

    if isinstance(value, dict):
        evidence_items = value.get("evidence")
        if isinstance(evidence_items, list):
            for evidence in evidence_items:
                if isinstance(evidence, dict):
                    yield evidence

        for key, nested in value.items():
            if key != "evidence":
                yield from _walk_evidence(nested)

    elif isinstance(value, list):
        for item in value:
            yield from _walk_evidence(item)


def _semantic_validation_status(result: dict) -> str:
    """Вычисляет общий статус только по результатам семантической проверки."""

    statuses = [
        item.get("relevance_status")
        for item in _walk_evidence(result)
        if isinstance(item.get("relevance_status"), str)
        and item.get("relevance_status") != "Цитата не найдена"
    ]

    if not statuses:
        return "Не требуется"

    completed = sum(
        status in {
            "Подтверждает",
            "Противоречит",
            "Недостаточно данных",
        }
        for status in statuses
    )
    failed = statuses.count("Проверка не выполнена")
    pending = len(statuses) - completed - failed

    if failed and not completed and not pending:
        return "Не выполнена"

    if failed or (completed and pending):
        return "Частично выполнена"

    if completed == len(statuses):
        return "Завершена"

    return "Не запускалась"


def _reset_failed_evidence(value) -> int:
    """Возвращает только неудавшиеся проверки в очередь повторной проверки."""

    reset_count = 0

    if isinstance(value, dict):
        if value.get("relevance_status") == "Проверка не выполнена":
            value["relevance_status"] = "Ожидает проверки"
            value["relevance_explanation"] = ""
            reset_count += 1

        for nested in value.values():
            reset_count += _reset_failed_evidence(nested)

    elif isinstance(value, list):
        for item in value:
            reset_count += _reset_failed_evidence(item)

    return reset_count


async def retry_semantic_validation(
    db: Session,
    document_id: int,
    analysis_id: int,
) -> dict:
    """Повторяет только семантическую проверку сохранённого результата."""

    # Атомарный захват до чтения результата: параллельный запрос не пройдёт.
    claim = (
        db.query(TenderAnalysisDB)
        .filter(
            TenderAnalysisDB.id == analysis_id,
            TenderAnalysisDB.document_id == document_id,
            TenderAnalysisDB.status == "Завершён",
            TenderAnalysisDB.semantic_validation_status != "Выполняется",
        )
        .update(
            {TenderAnalysisDB.semantic_validation_status: "Выполняется"},
            synchronize_session=False,
        )
    )

    if claim != 1:
        db.rollback()
        existing = (
            db.query(TenderAnalysisDB)
            .filter(
                TenderAnalysisDB.id == analysis_id,
                TenderAnalysisDB.document_id == document_id,
            )
            .first()
        )
        if existing is None:
            raise ValueError("Анализ не найден")
        if existing.status != "Завершён":
            raise ValueError("Основной анализ ещё не завершён")
        if existing.semantic_validation_status == "Выполняется":
            raise ValueError("Семантическая проверка уже выполняется")
        raise ValueError("Не удалось захватить анализ для повторной проверки")

    db.commit()
    db.expire_all()

    try:
        analysis = (
            db.query(TenderAnalysisDB)
            .filter(
                TenderAnalysisDB.id == analysis_id,
                TenderAnalysisDB.document_id == document_id,
            )
            .first()
        )

        if analysis is None:
            raise ValueError("Анализ не найден")

        if not isinstance(analysis.result_json, dict):
            raise ValueError("У анализа отсутствует сохранённый результат")

        technical_analysis = TechnicalAnalysis.model_validate(
            analysis.result_json
        )
        original_result = technical_analysis.model_dump()
        flattened = _flatten_requirement_items(original_result)

        records = (
            db.query(TenderRequirementDB)
            .filter(
                TenderRequirementDB.document_id == document_id,
                TenderRequirementDB.analysis_id == analysis_id,
            )
            .order_by(TenderRequirementDB.id)
            .all()
        )

        if len(records) != len(flattened):
            raise ValueError(
                "Количество сохранённых требований не совпадает с результатом анализа"
            )

        for record, (expected_type, _) in zip(records, flattened):
            if record.requirement_type != expected_type:
                raise ValueError(
                    "Порядок или тип сохранённых требований не совпадает "
                    "с результатом анализа"
                )

        retry_count = _reset_failed_evidence(original_result)
        if retry_count == 0:
            analysis.semantic_validation_status = (
                _semantic_validation_status(original_result)
            )
            db.commit()
            return {
                "analysis_id": analysis_id,
                "document_id": document_id,
                "semantic_validation_status": analysis.semantic_validation_status,
                "retried_evidence_count": 0,
                "message": "Нет доказательств с неудачной семантической проверкой",
            }

        technical_analysis = TechnicalAnalysis.model_validate(original_result)
        await validate_evidence_relevance(technical_analysis)

        updated_result = technical_analysis.model_dump()
        updated_items = _flatten_requirement_items(updated_result)

        if len(updated_items) != len(records):
            raise ValueError(
                "После проверки изменилось количество требований"
            )

        for record, (expected_type, item) in zip(records, updated_items):
            if record.requirement_type != expected_type:
                raise ValueError(
                    "После проверки изменился порядок типов требований"
                )

            record.attributes = {
                **item,
                "semantic_evidence_status": _semantic_evidence_status(item),
            }

        analysis.result_json = updated_result
        analysis.semantic_validation_status = (
            _semantic_validation_status(updated_result)
        )

        db.commit()
        db.refresh(analysis)

        return {
            "analysis_id": analysis_id,
            "document_id": document_id,
            "semantic_validation_status": analysis.semantic_validation_status,
            "retried_evidence_count": retry_count,
        }

    except Exception:
        db.rollback()
        failed_analysis = db.get(TenderAnalysisDB, analysis_id)
        if failed_analysis is not None:
            failed_analysis.semantic_validation_status = "Не выполнена"
            db.commit()
        raise


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
        analysis.semantic_validation_status = (
            _semantic_validation_status(result)
        )
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
