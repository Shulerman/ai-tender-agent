
import subprocess
from pathlib import Path


def extract_text_from_doc(file_path: str) -> str:
    """Извлекает текст из старого документа Word (.doc)."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {file_path}"
        )

    if path.suffix.lower() != ".doc":
        raise ValueError(
            "Поддерживаются только документы DOC"
        )

    result = subprocess.run(
        ["antiword", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=True,
    )

    text = result.stdout.strip()

    if not text:
        raise ValueError(
            "Не удалось извлечь текст из DOC"
        )

    return text



def extract_blocks_from_doc(file_path: str) -> list[dict]:
    """Извлекает логические текстовые блоки DOC с порядковыми координатами."""

    import re

    text = extract_text_from_doc(file_path)

    raw_blocks = re.split(r"\n\s*\n", text)
    blocks = []

    for block in raw_blocks:
        normalized_text = " ".join(block.split())

        if normalized_text:
            blocks.append({
                "locator_type": "text_block",
                "locator_value": str(len(blocks) + 1),
                "text": normalized_text,
            })

    if not blocks:
        raise ValueError("Не удалось извлечь текстовые блоки из DOC")

    return blocks
