from pathlib import Path
import os
import shutil
import subprocess
import tempfile

import camelot
import pdfplumber
import pypdfium2 as pdfium
from pypdf import PdfReader


TESSERACT_CANDIDATES = [
    os.environ.get("TESSERACT_CMD"),
    shutil.which("tesseract"),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
]
TESSDATA_CANDIDATES = [
    os.environ.get("TESSDATA_PREFIX"),
    str(Path.home() / "AppData/Local/Tesseract-OCR/tessdata"),
    r"C:\Program Files\Tesseract-OCR/tessdata",
]


def _tesseract_config():
    executable = next(
        (str(p) for p in TESSERACT_CANDIDATES if p and Path(p).is_file()),
        None,
    )
    tessdata = next(
        (str(p) for p in TESSDATA_CANDIDATES if p and Path(p).is_dir()),
        None,
    )
    return executable, tessdata


def _run_ocr(image):
    executable, tessdata = _tesseract_config()
    if not executable:
        return "", "Tesseract executable не найден"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
        image_path = Path(temp.name)
    try:
        image.save(image_path, format="PNG")
        command = [executable, str(image_path), "stdout", "-l", "rus+eng"]
        if tessdata:
            command.extend(["--tessdata-dir", tessdata])
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=180
        )
        if result.returncode != 0:
            return "", (result.stderr or "Ошибка Tesseract").strip()[:500]
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return "", "Превышено время OCR (180 секунд)"
    finally:
        image_path.unlink(missing_ok=True)


def _extract_tables(path, page_number):
    blocks = []
    warnings = []
    try:
        tables = camelot.read_pdf(
            str(path), pages=str(page_number), flavor="network"
        )
    except Exception as exc:
        return blocks, [f"Camelot network: {type(exc).__name__}: {exc}"]

    for table_index, table in enumerate(tables, start=1):
        rows = getattr(table, "cells", None) or []
        report = getattr(table, "parsing_report", {}) or {}
        for row_index, row in enumerate(rows, start=1):
            cells = [str(cell.text or "").strip() for cell in row]
            if not any(cells):
                continue
            cell_data = []
            for column_index, cell in enumerate(row, start=1):
                cell_data.append({
                    "row": row_index,
                    "column": column_index,
                    "text": str(cell.text or ""),
                    "coordinates": {
                        "x1": float(cell.x1),
                        "y1": float(cell.y1),
                        "x2": float(cell.x2),
                        "y2": float(cell.y2),
                    },
                })
            text = " | ".join(cells)
            blocks.append({
                "locator_type": "table_row",
                "locator_value": f"table={table_index};row={row_index}",
                "text": text,
                "metadata_json": {
                    "page_number": page_number,
                    "block_type": "table_row",
                    "extraction_method": "camelot_network",
                    "table_number": table_index,
                    "row_number": row_index,
                    "cells": cell_data,
                    "table_bbox": [
                        float(x) for x in getattr(table, "_bbox", ())
                    ],
                    "parsing_report": {
                        k: v for k, v in report.items()
                        if isinstance(v, (str, int, float, bool, type(None)))
                    },
                },
            })
    return blocks, warnings


def extract_pages_from_pdf(file_path: str) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported")

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("PDF зашифрован и требует пароль.")
        except Exception as exc:
            raise ValueError(
                f"Не удалось открыть зашифрованный PDF: {exc}"
            ) from exc

    document_metadata = {}
    if reader.metadata:
        document_metadata = {
            str(k): str(v) for k, v in reader.metadata.items()
            if v is not None
        }

    pages = []
    with pdfplumber.open(str(path)) as pdf:
        rendered_doc = pdfium.PdfDocument(str(path))
        try:
            for page_number, page in enumerate(pdf.pages, start=1):
                native_text = page.extract_text() or ""
                native_chars = len("".join(native_text.split()))
                warnings = []
                selected_text = native_text
                extraction_method = "pdfplumber_native"
                ocr_text = ""

                # OCR запускается на страницах с отсутствующим или очень
                # коротким текстовым слоем. Исходный текст сохраняется отдельно.
                if native_chars < 20:
                    try:
                        rendered = rendered_doc[page_number - 1].render(scale=2)
                        ocr_text, ocr_error = _run_ocr(rendered.to_pil())
                        if ocr_error:
                            warnings.append(ocr_error)
                        if ocr_text:
                            selected_text = ocr_text
                            extraction_method = "tesseract_ocr"
                        else:
                            warnings.append("OCR не вернул текст")
                    except Exception as exc:
                        warnings.append(
                            f"Рендеринг/OCR: {type(exc).__name__}: {exc}"
                        )
                elif page.images:
                    warnings.append(
                        "На странице есть изображения; OCR отдельных областей "
                        "пока не выполняется"
                    )

                page_metadata = {
                    "page_number": page_number,
                    "block_type": "page_text",
                    "extraction_method": extraction_method,
                    "native_text": native_text,
                    "ocr_text": ocr_text or None,
                    "native_character_count": native_chars,
                    "page_width": float(page.width),
                    "page_height": float(page.height),
                    "image_count": len(page.images),
                    "document_metadata": document_metadata,
                    "warnings": warnings,
                    "status": "warning" if warnings else "ok",
                }

                page_blocks = []
                if selected_text.strip():
                    page_blocks.append({
                        "locator_type": "page",
                        "locator_value": str(page_number),
                        "text": selected_text,
                        "metadata_json": page_metadata,
                    })

                table_blocks, table_warnings = _extract_tables(
                    path, page_number
                )
                page_blocks.extend(table_blocks)
                warnings.extend(table_warnings)
                page_metadata["warnings"] = warnings
                if warnings:
                    page_metadata["status"] = "warning"

                pages.append({
                    "page_number": page_number,
                    "text": selected_text,
                    "native_text": native_text,
                    "ocr_text": ocr_text,
                    "blocks": page_blocks,
                    "warnings": warnings,
                    "status": page_metadata["status"],
                })
        finally:
            rendered_doc.close()

    return pages


def extract_text_from_pdf(file_path: str) -> str:
    pages = extract_pages_from_pdf(file_path)
    return "\n".join(
        f"\n--- Страница {page['page_number']} ---\n{page['text']}"
        for page in pages
    ).strip()
