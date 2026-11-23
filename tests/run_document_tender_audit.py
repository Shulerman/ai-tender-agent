import os
import subprocess
from pathlib import Path
from docx import Document

from app.documents.extraction_service import extract_document_content

root = Path.cwd()
out = root / "tests"
docx_path = out / "tender_audit.docx"
doc_path = out / "tender_audit.doc"
pdf_path = out / "tender_audit.pdf"
html_path = out / "tender_audit.html"

products = [
    ("P-001", "Промышленный насос", "4", "шт.", "Производительность не менее 12 м³/ч"),
    ("P-002", "Электродвигатель", "2", "шт.", "Мощность не менее 5,5 кВт"),
    ("P-003", "Подшипник", "", "шт.", "Тип 6205, закрытый"),
    ("P-004", "Кабель силовой", "300", "м", "Сечение 4×2,5 мм²"),
]

attributes = [
    (f"Параметр {i:02d}", f"Значение {i:02d}", "обязательно" if i % 3 == 0 else "справочно")
    for i in range(1, 31)
]

d = Document()
d.add_heading("Техническое задание на поставку оборудования", level=1)
d.add_paragraph("Заказчик: ООО Тестовый заказчик")
d.add_paragraph("Предмет закупки: поставка промышленного оборудования и комплектующих.")
d.add_heading("1. Перечень товаров", level=2)

t = d.add_table(rows=1, cols=5)
for cell, value in zip(t.rows[0].cells, ["Артикул", "Наименование", "Количество", "Единица", "Требование"]):
    cell.text = value
for row in products:
    cells = t.add_row().cells
    for cell, value in zip(cells, row):
        cell.text = value

d.add_heading("2. Технические характеристики", level=2)
d.add_paragraph("Указанные ниже характеристики необходимо учитывать при подборе товаров.")
t2 = d.add_table(rows=1, cols=3)
for cell, value in zip(t2.rows[0].cells, ["Параметр", "Значение", "Статус"]):
    cell.text = value
for row in attributes:
    cells = t2.add_row().cells
    for cell, value in zip(cells, row):
        cell.text = value

d.add_heading("3. Условия поставки", level=2)
d.add_paragraph("Срок поставки: не позднее 20 рабочих дней с даты заключения договора.")
d.add_paragraph("Адрес поставки: склад заказчика, г. Москва.")
d.add_paragraph("Поставка одной партией. Разгрузка силами поставщика.")

d.add_heading("4. Документы поставщика", level=2)
d.add_paragraph("Предоставить паспорт качества, сертификат соответствия и инструкцию по эксплуатации.")
d.add_paragraph("Документы передаются вместе с товаром.")

d.add_heading("5. Дополнительные условия", level=2)
d.add_paragraph("Гарантийный срок — не менее 24 месяцев.")
d.add_paragraph("Цена должна включать упаковку, доставку и разгрузку.")
d.save(docx_path)

html_rows = "".join(
    "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
    for row in products
)
html_attributes = "".join(
    "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
    for row in attributes
)
html = f"""<!doctype html>
<html><head><title>Техническое задание</title></head><body>
<h1>Техническое задание на поставку оборудования</h1>
<p>Заказчик: ООО Тестовый заказчик</p>
<p>Предмет закупки: поставка промышленного оборудования и комплектующих.</p>
<h2>1. Перечень товаров</h2>
<table><tr><th>Артикул</th><th>Наименование</th><th>Количество</th><th>Единица</th><th>Требование</th></tr>{html_rows}</table>
<h2>2. Технические характеристики</h2>
<p>Указанные ниже характеристики необходимо учитывать при подборе товаров.</p>
<table><tr><th>Параметр</th><th>Значение</th><th>Статус</th></tr>{html_attributes}</table>
<h2>3. Условия поставки</h2>
<p>Срок поставки: не позднее 20 рабочих дней с даты заключения договора.</p>
<p>Адрес поставки: склад заказчика, г. Москва.</p>
<p>Поставка одной партией. Разгрузка силами поставщика.</p>
<h2>4. Документы поставщика</h2>
<p>Предоставить паспорт качества, сертификат соответствия и инструкцию по эксплуатации.</p>
<p>Документы передаются вместе с товаром.</p>
<h2>5. Дополнительные условия</h2>
<p>Гарантийный срок — не менее 24 месяцев.</p>
<p>Цена должна включать упаковку, доставку и разгрузку.</p>
</body></html>"""
html_path.write_text(html, encoding="utf-8")

ps_script = r"""
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
    "AUDIT_DOCX": str(docx_path),
    "AUDIT_DOC": str(doc_path),
    "AUDIT_PDF": str(pdf_path),
})
result = subprocess.run(
    ["powershell.exe", "-NoProfile", "-STA", "-NonInteractive",
     "-ExecutionPolicy", "Bypass", "-Command", ps_script],
    capture_output=True, text=True, encoding="utf-8",
    errors="replace", timeout=180, env=env,
)
if result.returncode or not doc_path.exists() or not pdf_path.exists():
    raise RuntimeError("Word export failed: " + (result.stderr or result.stdout)[-2000:])

expected = [
    "Промышленный насос",
    "Электродвигатель",
    "Подшипник",
    "Кабель силовой",
    "Параметр 30",
    "20 рабочих дней",
    "склад заказчика",
    "паспорт качества",
    "сертификат соответствия",
    "24 месяцев",
    "упаковку, доставку и разгрузку",
]

for name, path in [
    ("DOCX", docx_path),
    ("DOC", doc_path),
    ("PDF", pdf_path),
    ("HTML", html_path),
]:
    data = extract_document_content(str(path))
    text = data["text"]
    missing = [item for item in expected if item not in text]
    blocks = data["blocks"]
    print(f"\n========== {name} ==========")
    print("BLOCKS:", len(blocks))
    print("TABLE ROW BLOCKS:", sum(b["locator_type"] == "table_row" for b in blocks))
    print("PAGES:", sum(b["locator_type"] == "page" for b in blocks))
    print("EXPECTED MARKERS:", len(expected) - len(missing), "/", len(expected))
    print("MISSING:", missing if missing else "нет")
    print("MISSING QUANTITY ROW PRESERVED:", "P-003" in text and "Подшипник" in text)
    print("FIRST BLOCK:", repr(blocks[0]["text"][:140]) if blocks else "нет блоков")
    print("LAST BLOCK:", repr(blocks[-1]["text"][:140]) if blocks else "нет блоков")
