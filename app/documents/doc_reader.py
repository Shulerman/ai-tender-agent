import os
import subprocess
import tempfile
from pathlib import Path

from app.documents.docx_reader import extract_blocks_from_docx


def _validate_doc_path(file_path: str) -> Path:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")
    if path.suffix.lower() != ".doc":
        raise ValueError("Поддерживаются только документы DOC")
    return path


def _convert_doc_to_docx(source: Path, destination: Path) -> None:
    """Конвертирует DOC в DOCX через Microsoft Word COM в Windows."""
    if os.name != "nt":
        raise RuntimeError(
            "Обработка DOC требует Windows и установленного Microsoft Word."
        )

    script = r"""
$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $document = $word.Documents.Open(
        $env:AI_TENDER_DOC_INPUT,
        $false,
        $true,
        $false
    )
    $document.SaveAs2($env:AI_TENDER_DOC_OUTPUT, 16)
}
finally {
    if ($null -ne $document) {
        $document.Close(0)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($document)
    }
    if ($null -ne $word) {
        $word.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
}
"""
    env = os.environ.copy()
    env["AI_TENDER_DOC_INPUT"] = str(source.resolve())
    env["AI_TENDER_DOC_OUTPUT"] = str(destination.resolve())

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Истекло время конвертации DOC через Microsoft Word") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("Не найден Windows PowerShell для конвертации DOC") from exc

    if result.returncode != 0 or not destination.exists():
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "Не удалось конвертировать DOC через Microsoft Word"
            + (f": {details[-1500:]}" if details else "")
        )


def extract_blocks_from_doc(file_path: str) -> list[dict]:
    """Извлекает абзацы и строки таблиц DOC через временную конвертацию в DOCX."""
    source = _validate_doc_path(file_path)

    with tempfile.TemporaryDirectory(prefix="ai_tender_doc_") as temp_dir:
        converted = Path(temp_dir) / "converted.docx"
        _convert_doc_to_docx(source, converted)
        return extract_blocks_from_docx(str(converted))


def extract_text_from_doc(file_path: str) -> str:
    """Извлекает текст DOC с сохранением порядка абзацев и строк таблиц."""
    blocks = extract_blocks_from_doc(file_path)
    return "\n".join(block["text"] for block in blocks)
