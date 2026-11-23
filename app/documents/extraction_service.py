import re
from pathlib import Path

from app.documents.pdf_reader import extract_pages_from_pdf
from app.documents.docx_reader import extract_blocks_from_docx
from app.documents.doc_reader import extract_blocks_from_doc
from app.documents.html_reader import extract_blocks_from_html


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".html"}


def _normalize_pdf_text(value: str) -> str:
    # Сохраняем смысловые переносы строк, убирая лишние пробелы.
    lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def extract_document_content(file_path: str) -> dict:
    """
    Возвращает совместимый интерфейс text/blocks.
    PDF-блоки дополнительно содержат provenance в metadata_json.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("Поддерживаются только PDF, DOCX, DOC и HTML.")

    is_pdf = extension == ".pdf"
    if is_pdf:
        source_blocks = []
        for page in extract_pages_from_pdf(str(path)):
            page_blocks = page.get("blocks") or [{
                "locator_type": "page",
                "locator_value": str(page["page_number"]),
                "text": page.get("text", ""),
                "metadata_json": {
                    "page_number": page["page_number"],
                    "block_type": "page_text",
                    "extraction_method": "legacy_pdf_reader",
                },
            }]
            source_blocks.extend(page_blocks)
    elif extension == ".docx":
        source_blocks = extract_blocks_from_docx(str(path))
    elif extension == ".doc":
        source_blocks = extract_blocks_from_doc(str(path))
    else:
        source_blocks = extract_blocks_from_html(str(path))

    blocks = []
    text_parts = []
    previous_table = None

    for source_block in source_blocks:
        locator_type = source_block["locator_type"]
        raw_text = source_block.get("text", "")
        text = (
            _normalize_pdf_text(raw_text)
            if is_pdf else " ".join(raw_text.split())
        )
        if not text:
            continue

        locator_value = source_block.get("locator_value")
        block = {
            "sequence_number": len(blocks) + 1,
            "locator_type": locator_type,
            "locator_value": locator_value,
            "text": text,
            "metadata_json": source_block.get("metadata_json"),
        }
        blocks.append(block)

        if locator_type == "page":
            text_parts.append(f"--- Страница {locator_value} ---")
            text_parts.append(text)
            previous_table = None
        elif locator_type == "table_row":
            table_number = None
            if locator_value and str(locator_value).startswith("table="):
                table_number = str(locator_value).split(";", 1)[0]
            if table_number and table_number != previous_table:
                text_parts.append(
                    f"--- Таблица {table_number.split('=')[-1]} "
                    f"(структурное извлечение) ---"
                )
            previous_table = table_number
            text_parts.append(text)
        else:
            previous_table = None
            text_parts.append(text)

    if not blocks:
        raise ValueError("В документе не найден текст для обработки.")

    return {"text": "\n".join(text_parts).strip(), "blocks": blocks}


def extract_document_blocks(file_path: str) -> list[dict]:
    """Обратная совместимость со старым интерфейсом извлечения блоков."""
    return extract_document_content(file_path)["blocks"]
