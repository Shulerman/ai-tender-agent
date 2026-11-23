from docx import Document

from app.documents import doc_reader, extraction_service
from app.documents.extraction_service import extract_document_content


def test_pdf_extraction_preserves_page_locators(tmp_path, monkeypatch):
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-test")

    calls = []
    def fake_pages(file_path):
        calls.append(file_path)
        return [
            {"page_number": 1, "text": "Требование по товару"},
            {"page_number": 2, "text": "Поставка за 10 дней"},
        ]

    monkeypatch.setattr(extraction_service, "extract_pages_from_pdf", fake_pages)
    result = extract_document_content(str(path))

    assert len(calls) == 1
    assert [b["locator_type"] for b in result["blocks"]] == ["page", "page"]
    assert [b["locator_value"] for b in result["blocks"]] == ["1", "2"]
    assert "Страница 1" in result["text"]
    assert "Поставка за 10 дней" in result["text"]


def test_docx_extraction_preserves_paragraphs_and_table_rows(tmp_path):
    path = tmp_path / "sample.docx"
    document = Document()
    document.add_paragraph("Требования к изделию")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Диаметр"
    table.cell(0, 1).text = "20 мм"
    document.add_paragraph("Срок поставки 10 дней")
    document.save(path)

    result = extract_document_content(str(path))

    assert [b["locator_type"] for b in result["blocks"]] == [
        "paragraph", "table_row", "paragraph"
    ]
    assert result["blocks"][1]["text"] == "Диаметр | 20 мм"
    assert "Таблица 1" in result["text"]
    assert result["text"].index("Диаметр") < result["text"].index("Срок поставки")


def test_doc_extraction_uses_word_conversion_and_docx_parser(tmp_path, monkeypatch):
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"fake doc")
    converted_blocks = [
        {
            "locator_type": "paragraph",
            "locator_value": "1",
            "text": "Требование из DOC",
        }
    ]

    def fake_convert(source_path, destination):
        document = Document()
        document.add_paragraph("Требование из DOC")
        document.save(destination)

    monkeypatch.setattr(doc_reader, "_convert_doc_to_docx", fake_convert)

    from app.documents.doc_reader import extract_blocks_from_doc
    blocks = extract_blocks_from_doc(str(source))

    assert len(blocks) == 1
    assert blocks[0]["text"] == "Требование из DOC"
    assert blocks[0]["locator_type"] == "paragraph"


def test_html_extraction_preserves_heading_and_paragraph(tmp_path):
    path = tmp_path / "sample.html"
    path.write_text(
        "<html><body><h1>Техническое задание</h1>"
        "<p>Количество 15 штук</p></body></html>",
        encoding="utf-8",
    )

    result = extract_document_content(str(path))

    assert len(result["blocks"]) == 2
    assert result["blocks"][0]["text"] == "Техническое задание"
    assert result["blocks"][1]["text"] == "Количество 15 штук"


def test_extraction_rejects_document_without_text(tmp_path, monkeypatch):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"%PDF-test")
    monkeypatch.setattr(
        extraction_service,
        "extract_pages_from_pdf",
        lambda _: [{"page_number": 1, "text": ""}],
    )

    import pytest
    with pytest.raises(ValueError, match="не найден текст"):
        extract_document_content(str(path))


def test_docx_text_uses_real_line_breaks(tmp_path):
    path = tmp_path / "linebreaks.docx"
    document = Document()
    document.add_paragraph("Первый абзац")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Строка таблицы"
    document.add_paragraph("Последний абзац")
    document.save(path)

    from app.documents.docx_reader import extract_text_from_docx
    text = extract_text_from_docx(str(path))

    assert "\\\\n" not in text
    assert "\n--- Таблица 1 ---" in text
    assert text.index("Первый абзац") < text.index("Строка таблицы")
    assert text.index("Строка таблицы") < text.index("Последний абзац")
