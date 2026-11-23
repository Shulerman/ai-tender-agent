from docx import Document

from app.documents.docx_reader import (
    extract_blocks_from_docx,
    extract_text_from_docx,
)


def _make_mixed_docx(path):
    document = Document()
    document.add_paragraph("Первый абзац")
    table1 = document.add_table(rows=1, cols=2)
    table1.cell(0, 0).text = "Товар А"
    table1.cell(0, 1).text = "Количество 10"
    document.add_paragraph("Условия поставки")
    table2 = document.add_table(rows=1, cols=2)
    table2.cell(0, 0).text = "Товар Б"
    table2.cell(0, 1).text = "Количество 20"
    document.add_paragraph("Заключительный абзац")
    document.save(path)


def test_extract_blocks_preserves_paragraph_and_table_order(tmp_path):
    path = tmp_path / "mixed.docx"
    _make_mixed_docx(path)

    blocks = extract_blocks_from_docx(str(path))

    assert [block["locator_type"] for block in blocks] == [
        "paragraph", "table_row", "paragraph", "table_row", "paragraph"
    ]
    assert [block["text"] for block in blocks] == [
        "Первый абзац",
        "Товар А | Количество 10",
        "Условия поставки",
        "Товар Б | Количество 20",
        "Заключительный абзац",
    ]
    assert blocks[1]["locator_value"] == "table=1;row=1"
    assert blocks[3]["locator_value"] == "table=2;row=1"


def test_extract_text_preserves_paragraph_and_table_order(tmp_path):
    path = tmp_path / "mixed.docx"
    _make_mixed_docx(path)

    text = extract_text_from_docx(str(path))

    positions = [
        text.index("Первый абзац"),
        text.index("Товар А"),
        text.index("Условия поставки"),
        text.index("Товар Б"),
        text.index("Заключительный абзац"),
    ]
    assert positions == sorted(positions)

def test_merged_cells_are_not_duplicated(tmp_path):
    path = tmp_path / "merged.docx"
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Объединённый заголовок"
    document.save(path)

    blocks = extract_blocks_from_docx(str(path))

    assert len(blocks) == 1
    assert blocks[0]["text"] == "Объединённый заголовок"


def test_nested_table_is_extracted_with_parent_locator(tmp_path):
    path = tmp_path / "nested.docx"
    document = Document()
    document.add_paragraph("Начало")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Основная ячейка"
    nested = table.cell(0, 1).add_table(rows=1, cols=2)
    nested.cell(0, 0).text = "Вложенный параметр"
    nested.cell(0, 1).text = "42 мм"
    document.add_paragraph("Конец")
    document.save(path)

    blocks = extract_blocks_from_docx(str(path))

    assert any("Вложенный параметр | 42 мм" == block["text"] for block in blocks)
    nested_block = next(
        block for block in blocks
        if "Вложенный параметр" in block["text"]
    )
    assert "parent_table=1" in nested_block["locator_value"]
    assert "parent_row=1" in nested_block["locator_value"]
    assert "cell=2" in nested_block["locator_value"]
    assert blocks[0]["text"] == "Начало"
    assert blocks[-1]["text"] == "Конец"
