from pathlib import Path
from docx import Document


def extract_text_from_docx(file_path: str) -> str:
    """
    Извлекает текст и таблицы из Word-документа.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if path.suffix.lower() != ".docx":
        raise ValueError("Only DOCX files are supported")

    document = Document(str(path))
    content = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            content.append(text)

    for table_number, table in enumerate(document.tables, start=1):
        content.append(f"\n--- Таблица {table_number} ---")

        for row in table.rows:
            cells = [
                cell.text.strip().replace("\n", " ")
                for cell in row.cells
            ]
            content.append(" | ".join(cells))

    return "\n".join(content).strip()
