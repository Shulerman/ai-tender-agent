from pathlib import Path

from app.documents.pdf_reader import extract_pages_from_pdf
from app.documents.docx_reader import extract_blocks_from_docx
from app.documents.doc_reader import extract_blocks_from_doc
from app.documents.html_reader import extract_blocks_from_html


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".html"}


def extract_document_blocks(file_path: str) -> list[dict]:
    """
    Извлекает структурированные фрагменты документа любого поддерживаемого формата.

    Каждый результат содержит:
    - sequence_number: сквозной номер фрагмента;
    - locator_type: тип координаты источника;
    - locator_value: значение координаты;
    - text: текст фрагмента;
    - metadata_json: дополнительные метаданные.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            "Поддерживаются только PDF, DOCX, DOC и HTML."
        )

    if extension == ".pdf":
        source_blocks = [
            {
                "locator_type": "page",
                "locator_value": str(page["page_number"]),
                "text": page["text"],
            }
            for page in extract_pages_from_pdf(str(path))
        ]
    elif extension == ".docx":
        source_blocks = extract_blocks_from_docx(str(path))
    elif extension == ".doc":
        source_blocks = extract_blocks_from_doc(str(path))
    else:
        source_blocks = extract_blocks_from_html(str(path))

    result = []

    for block in source_blocks:
        text = " ".join(block.get("text", "").split())

        if not text:
            continue

        result.append({
            "sequence_number": len(result) + 1,
            "locator_type": block["locator_type"],
            "locator_value": block.get("locator_value"),
            "text": text,
            "metadata_json": None,
        })

    if not result:
        raise ValueError(
            "В документе не найден текст для обработки."
        )

    return result
