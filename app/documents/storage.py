
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


DOCUMENTS_DIR = Path("data/documents")


async def save_document(file: UploadFile) -> dict:
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    original_name = Path(
        file.filename or "document"
    ).name

    content = await file.read()

    if not content:
        raise ValueError("Загруженный файл пуст")

    signature = content.lstrip(
        b"\xef\xbb\xbf \t\r\n"
    ).lower()

    if content.startswith(b"%PDF-"):
        extension = ".pdf"

    elif content.startswith(b"PK\x03\x04"):
        extension = ".docx"

    elif content.startswith(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    ):
        extension = ".doc"

    elif (
        signature.startswith(b"<!doctype html")
        or signature.startswith(b"<html")
    ):
        extension = ".html"

    else:
        raise ValueError(
            "Неизвестный формат файла. "
            "Поддерживаются PDF, DOCX, DOC и HTML."
        )

    document_id = str(uuid4())
    saved_path = DOCUMENTS_DIR / f"{document_id}{extension}"

    saved_path.write_bytes(content)

    return {
        "document_id": document_id,
        "original_name": original_name,
        "file_path": str(saved_path),
        "size_bytes": len(content),
        "detected_extension": extension,
    }
