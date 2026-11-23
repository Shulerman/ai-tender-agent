import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from docx import Document
from app.documents.extraction_service import extract_document_content

with TemporaryDirectory(prefix="ai_tender_edge_audit_") as temp:
    root = Path(temp)

    # DOCX: объединённые ячейки и вложенная таблица.
    docx_path = root / "edge.docx"
    doc = Document()
    doc.add_paragraph("Начало документа")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Объединённый заголовок"
    table.cell(1, 0).text = "Основная ячейка"
    nested = table.cell(1, 1).add_table(rows=1, cols=2)
    nested.cell(0, 0).text = "Вложенный параметр"
    nested.cell(0, 1).text = "42 мм"
    doc.add_paragraph("Конец документа")
    doc.save(docx_path)

    # HTML: вложенные элементы, две таблицы, title и незакрытые теги.
    html_path = root / "edge.html"
    html_path.write_text(
        '<!doctype html><html><head><title>Служебный заголовок</title></head>'
        '<body><h1>Начало документа</h1>'
        '<div><p>Требование <b>с повышенной прочностью</b></p></div>'
        '<table><tr><th>Параметр</th><th>Значение</th></tr>'
        '<tr><td>Диаметр</td><td>25 мм</td></tr></table>'
        '<p>Промежуточный текст'
        '<table><tr><td>Срок</td><td>15 дней</td></tr></table>'
        '<p>Конец документа</body></html>',
        encoding="utf-8",
    )

    for name, path in [("DOCX", docx_path), ("HTML", html_path)]:
        print(f"\n========== {name} EDGE CASE ==========")
        try:
            result = extract_document_content(str(path))
            for block in result["blocks"]:
                print(
                    block["sequence_number"],
                    block["locator_type"],
                    block["locator_value"],
                    repr(block["text"]),
                )
        except Exception as exc:
            print("ERROR:", type(exc).__name__, str(exc))
