import json
import subprocess
import tempfile
from pathlib import Path

from docx import Document

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.documents.extraction_service import extract_document_content

EXPECTED = [
    "ТЕХНИЧЕСКОЕ ЗАДАНИЕ",
    "Подшипник радиальный",
    "B-6205",
    "Количество",
    "120",
    "штук",
    "Внутренний диаметр",
    "25 мм",
    "Наружный диаметр",
    "52 мм",
    "Срок поставки",
    "15 рабочих дней",
    "Документы качества",
    "паспорт изделия",
]

def create_docx(path):
    doc = Document()
    doc.add_heading("ТЕХНИЧЕСКОЕ ЗАДАНИЕ", level=1)
    doc.add_paragraph("Предмет закупки: поставка подшипников.")
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for cell, value in zip(table.rows[0].cells, ["Наименование", "Артикул", "Количество"]):
        cell.text = value
    row = table.add_row()
    for cell, value in zip(row.cells, ["Подшипник радиальный", "B-6205", "120 штук"]):
        cell.text = value
    doc.add_paragraph("Технические характеристики:")
    table2 = doc.add_table(rows=1, cols=2)
    table2.style = "Table Grid"
    for cell, value in zip(table2.rows[0].cells, ["Параметр", "Значение"]):
        cell.text = value
    for left, right in [
        ("Внутренний диаметр", "25 мм"),
        ("Наружный диаметр", "52 мм"),
    ]:
        cells = table2.add_row().cells
        cells[0].text = left
        cells[1].text = right
    doc.add_paragraph("Срок поставки: 15 рабочих дней.")
    doc.add_paragraph("Документы качества: паспорт изделия.")
    doc.save(path)

def create_word_exports(docx_path, doc_path, pdf_path):
    script = r"""
$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $document = $word.Documents.Open($env:AUDIT_DOCX, $false, $true, $false)
    $document.SaveAs2($env:AUDIT_DOC, 0)
    $document.ExportAsFixedFormat($env:AUDIT_PDF, 17)
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
    import os
    env = os.environ.copy()
    env.update({
        "AUDIT_DOCX": str(docx_path.resolve()),
        "AUDIT_DOC": str(doc_path.resolve()),
        "AUDIT_PDF": str(pdf_path.resolve()),
    })
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180, env=env,
    )
    if result.returncode or not doc_path.exists() or not pdf_path.exists():
        raise RuntimeError(
            "Word export failed: " + (result.stderr or result.stdout)[-2000:]
        )

def create_html(path):
    path.write_text("""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Тендер</title></head>
<body>
<h1>ТЕХНИЧЕСКОЕ ЗАДАНИЕ</h1>
<p>Предмет закупки: поставка подшипников.</p>
<table>
<tr><th>Наименование</th><th>Артикул</th><th>Количество</th></tr>
<tr><td>Подшипник радиальный</td><td>B-6205</td><td>120 штук</td></tr>
</table>
<p>Технические характеристики:</p>
<table>
<tr><th>Параметр</th><th>Значение</th></tr>
<tr><td>Внутренний диаметр</td><td>25 мм</td></tr>
<tr><td>Наружный диаметр</td><td>52 мм</td></tr>
</table>
<p>Срок поставки: 15 рабочих дней.</p>
<p>Документы качества: паспорт изделия.</p>
</body></html>""", encoding="utf-8")

with tempfile.TemporaryDirectory(prefix="ai_tender_format_audit_") as temp:
    root = Path(temp)
    paths = {
        "DOCX": root / "control.docx",
        "DOC": root / "control.doc",
        "PDF": root / "control.pdf",
        "HTML": root / "control.html",
    }
    create_docx(paths["DOCX"])
    create_word_exports(paths["DOCX"], paths["DOC"], paths["PDF"])
    create_html(paths["HTML"])

    report = {}
    failures = []
    for fmt, path in paths.items():
        result = extract_document_content(str(path))
        text = result["text"]
        missing = [item for item in EXPECTED if item.casefold() not in text.casefold()]
        blocks = result["blocks"]
        report[fmt] = {
            "file_bytes": path.stat().st_size,
            "block_count": len(blocks),
            "locator_types": sorted({b["locator_type"] for b in blocks}),
            "missing_expected_fragments": missing,
            "first_blocks": [
                {
                    "locator_type": b["locator_type"],
                    "locator_value": b["locator_value"],
                    "text": b["text"],
                }
                for b in blocks[:8]
            ],
        }
        if missing:
            failures.append(fmt)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("AUDIT FAILED: missing content in " + ", ".join(failures))
    print("\nALL FOUR FORMATS: BASELINE CONTENT CHECK PASSED")
