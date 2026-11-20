from pathlib import Path
from pypdf import PdfReader


def extract_pages_from_pdf(file_path: str) -> list[dict]:
    """
    Извлекает текст PDF с сохранением границ и номеров страниц.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported")

    reader = PdfReader(str(path))

    return [
        {
            "page_number": page_number,
            "text": page.extract_text() or "",
        }
        for page_number, page in enumerate(reader.pages, start=1)
    ]


def extract_text_from_pdf(file_path: str) -> str:
    """
    Извлекает текст из PDF-документа в прежнем текстовом формате.
    """

    pages = extract_pages_from_pdf(file_path)

    return "\n".join(
        f"\n--- Страница {page['page_number']} ---\n{page['text']}"
        for page in pages
    ).strip()
