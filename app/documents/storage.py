from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


DOCUMENTS_DIR = Path("data/documents")
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


async def save_document(file: UploadFile) -> dict:
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    original_name = Path(file.filename or "document.pdf").name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Поддерживаются только PDF и DOCX")

    document_id = str(uuid4())
    saved_path = DOCUMENTS_DIR / f"{document_id}{extension}"

    content = await file.read()

    if not content:
        raise ValueError("Загруженный файл пуст")

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("Файл не является корректным PDF")

    if extension == ".docx" and not content.startswith(b"PK"):
        raise ValueError("Файл не является корректным DOCX")

    saved_path.write_bytes(content)

    return {
        "document_id": document_id,
        "original_name": original_name,
        "file_path": str(saved_path),
        "size_bytes": len(content)
    }
