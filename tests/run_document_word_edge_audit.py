import os
import subprocess
from pathlib import Path
from docx import Document

root = Path.cwd()
docx = root / "tests" / "edge.docx"
doc = root / "tests" / "edge.doc"
pdf = root / "tests" / "edge.pdf"

# Создаём контрольный документ с объединёнными и вложенными ячейками.
d = Document()
d.add_paragraph("Начало документа")
table = d.add_table(rows=2, cols=2)
table.cell(0, 0).merge(table.cell(0, 1))
table.cell(0, 0).text = "Объединённый заголовок"
table.cell(1, 0).text = "Основная ячейка"
nested = table.cell(1, 1).add_table(rows=1, cols=2)
nested.cell(0, 0).text = "Вложенный параметр"
nested.cell(0, 1).text = "42 мм"
d.add_paragraph("Конец документа")
d.add_page_break()
d.add_paragraph("ВТОРАЯ СТРАНИЦА")
d.add_paragraph("Срок поставки: 15 рабочих дней")
d.save(docx)

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
env = os.environ.copy()
env.update({
    "AUDIT_DOCX": str(docx),
    "AUDIT_DOC": str(doc),
    "AUDIT_PDF": str(pdf),
})
result = subprocess.run(
    ["powershell.exe", "-NoProfile", "-STA", "-NonInteractive",
     "-ExecutionPolicy", "Bypass", "-Command", script],
    capture_output=True, text=True, encoding="utf-8",
    errors="replace", timeout=180, env=env,
)
if result.returncode or not doc.exists() or not pdf.exists():
    raise RuntimeError("Word export failed: " + (result.stderr or result.stdout)[-2000:])

from app.documents.extraction_service import extract_document_content

for name, path in [("DOCX", docx), ("DOC", doc), ("PDF", pdf)]:
    print(f"\n========== {name} EDGE CASE ==========")
    data = extract_document_content(str(path))
    for block in data["blocks"]:
        print(block["sequence_number"], block["locator_type"],
              block["locator_value"], repr(block["text"]))
    print("NESTED VALUE PRESERVED:", "42 мм" in data["text"])
    print("SECOND PAGE PRESERVED:", "ВТОРАЯ СТРАНИЦА" in data["text"])
    print("PAGE COUNT:", len([b for b in data["blocks"] if b["locator_type"] == "page"]))
