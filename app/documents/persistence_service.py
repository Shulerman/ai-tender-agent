from sqlalchemy.orm import Session

from app.documents.models import (
    TenderDocumentDB,
    DocumentChunkDB,
)


def save_document_with_chunks(
    db: Session,
    document: dict,
    blocks: list[dict],
    tender_id: int | None = None,
) -> TenderDocumentDB:
    """
    Атомарно сохраняет документ и все его текстовые фрагменты.

    Файл должен быть предварительно сохранён на диск,
    а blocks должны быть получены через extract_document_blocks().
    """

    required_fields = {
        "document_id",
        "original_name",
        "file_path",
        "detected_extension",
        "size_bytes",
    }

    missing_fields = required_fields - document.keys()

    if missing_fields:
        raise ValueError(
            f"Отсутствуют поля документа: {sorted(missing_fields)}"
        )

    if not blocks:
        raise ValueError("Нельзя сохранить документ без текстовых фрагментов")

    validated_blocks = []
    seen_sequences = set()

    for block in blocks:
        sequence_number = block.get("sequence_number")
        locator_type = block.get("locator_type")
        locator_value = block.get("locator_value")
        text = block.get("text")

        if not isinstance(sequence_number, int) or sequence_number < 1:
            raise ValueError("Некорректный sequence_number")

        if sequence_number in seen_sequences:
            raise ValueError(
                f"Повторяется sequence_number: {sequence_number}"
            )

        if not locator_type:
            raise ValueError("Не указан locator_type")

        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"Пустой текст фрагмента №{sequence_number}"
            )

        seen_sequences.add(sequence_number)

        validated_blocks.append({
            "sequence_number": sequence_number,
            "locator_type": locator_type,
            "locator_value": locator_value,
            "text": text,
            "metadata_json": block.get("metadata_json"),
        })

    validated_blocks.sort(key=lambda item: item["sequence_number"])

    if [b["sequence_number"] for b in validated_blocks] != list(
        range(1, len(validated_blocks) + 1)
    ):
        raise ValueError(
            "Номера фрагментов должны идти последовательно от 1"
        )

    try:
        document_record = TenderDocumentDB(
            document_uuid=document["document_id"],
            tender_id=tender_id,
            original_name=document["original_name"],
            file_path=document["file_path"],
            file_hash=document.get("file_hash"),
            detected_extension=document["detected_extension"],
            size_bytes=document["size_bytes"],
            processing_status="Фрагменты извлечены",
        )

        db.add(document_record)
        db.flush()

        chunks = [
            DocumentChunkDB(
                document_id=document_record.id,
                sequence_number=block["sequence_number"],
                locator_type=block["locator_type"],
                locator_value=block["locator_value"],
                text=block["text"],
                metadata_json=block["metadata_json"],
            )
            for block in validated_blocks
        ]

        db.add_all(chunks)
        db.commit()
        db.refresh(document_record)

        return document_record

    except Exception:
        db.rollback()
        raise
