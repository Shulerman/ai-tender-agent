from pathlib import Path
from docx import Document


def _validate_docx_path(file_path: str) -> Path:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.suffix.lower() != ".docx":
        raise ValueError("Only DOCX files are supported")
    return path


def _iter_table_rows(table, table_number: int, table_counter: list[int], parent_locator: str | None = None):
    """Рекурсивно извлекает строки таблиц, включая вложенные таблицы."""
    for row_number, row in enumerate(table.rows, start=1):
        cells = []
        nested_tables = []
        seen_cells = set()

        for column_number, cell in enumerate(row.cells, start=1):
            cell_identity = id(cell._tc)

            # python-docx возвращает одну и ту же ячейку несколько раз
            # для горизонтально объединённых ячеек.
            if cell_identity in seen_cells:
                continue
            seen_cells.add(cell_identity)

            paragraph_text = [
                " ".join(paragraph.text.split())
                for paragraph in cell.paragraphs
            ]
            cell_text = " ".join(part for part in paragraph_text if part)
            cells.append(cell_text)

            for child in cell.iter_inner_content():
                if hasattr(child, "rows"):
                    nested_tables.append((column_number, child))

        text = " | ".join(cells)
        if text.strip():
            locator = f"table={table_number};row={row_number}"
            if parent_locator:
                locator += f";{parent_locator}"
            yield {
                "locator_type": "table_row",
                "locator_value": locator,
                "text": text,
            }

        for column_number, nested_table in nested_tables:
            table_counter[0] += 1
            nested_number = table_counter[0]
            nested_parent = (
                f"parent_table={table_number};"
                f"parent_row={row_number};cell={column_number}"
            )
            yield from _iter_table_rows(
                nested_table,
                nested_number,
                table_counter,
                nested_parent,
            )


def extract_blocks_from_docx(file_path: str) -> list[dict]:
    """Извлекает абзацы и строки всех таблиц в порядке документа."""
    document = Document(str(_validate_docx_path(file_path)))
    blocks = []
    paragraph_number = 0
    table_counter = [0]

    for block in document.iter_inner_content():
        if hasattr(block, "rows"):
            table_counter[0] += 1
            blocks.extend(
                _iter_table_rows(block, table_counter[0], table_counter)
            )
        else:
            paragraph_number += 1
            text = block.text.strip()
            if text:
                blocks.append({
                    "locator_type": "paragraph",
                    "locator_value": str(paragraph_number),
                    "text": text,
                })

    return blocks


def extract_text_from_docx(file_path: str) -> str:
    """Извлекает текст DOCX с сохранением порядка и границ таблиц."""
    blocks = extract_blocks_from_docx(file_path)
    content = []
    previous_table = None

    for block in blocks:
        locator = block["locator_value"]
        if block["locator_type"] == "table_row":
            table_number = locator.split(";", 1)[0]
            if table_number != previous_table:
                content.append(
                    f"\n--- Таблица {table_number.split('=')[-1]} ---"
                )
            previous_table = table_number
        else:
            previous_table = None

        content.append(block["text"])

    return "\n".join(content).strip()
