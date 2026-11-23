from app.documents.html_reader import extract_blocks_from_html


def test_html_ignores_head_and_preserves_table_coordinates(tmp_path):
    path = tmp_path / "head_and_tables.html"
    path.write_text(
        "<html><head><title>Служебный заголовок</title></head><body>"
        "<h1>Техническое задание</h1>"
        "<table><tr><th>Название</th><th>Количество</th></tr>"
        "<tr><td>Насос</td><td>4 шт.</td></tr></table>"
        "<p>Условия поставки</p>"
        "<table><tr><td>Срок</td><td>20 дней</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )

    blocks = extract_blocks_from_html(str(path))

    assert all("Служебный заголовок" not in b["text"] for b in blocks)
    rows = [b for b in blocks if b["locator_type"] == "table_row"]
    assert [b["locator_value"] for b in rows] == [
        "table=1;row=1",
        "table=1;row=2",
        "table=2;row=1",
    ]
    assert rows[1]["text"] == "Насос | 4 шт."


def test_html_malformed_nested_paragraphs_keep_source_order(tmp_path):
    path = tmp_path / "malformed.html"
    path.write_text(
        "<html><body>"
        "<p>Начальный текст"
        "<table><tr><td>Строка таблицы</td></tr></table>"
        "<p>Промежуточный текст"
        "<p>Последний текст</p>"
        "</body></html>",
        encoding="utf-8",
    )

    blocks = extract_blocks_from_html(str(path))
    texts = [b["text"] for b in blocks]

    expected = [
        "Начальный текст",
        "Строка таблицы",
        "Промежуточный текст",
        "Последний текст",
    ]
    positions = [texts.index(item) for item in expected]
    assert positions == sorted(positions)


def test_html_skips_script_and_style_content(tmp_path):
    path = tmp_path / "ignored.html"
    path.write_text(
        "<html><head><title>Не включать</title></head><body>"
        "<script>secret_script()</script>"
        "<style>.secret { display: none; }</style>"
        "<p>Полезное требование</p>"
        "</body></html>",
        encoding="utf-8",
    )

    blocks = extract_blocks_from_html(str(path))
    text = " ".join(block["text"] for block in blocks)

    assert "Полезное требование" in text
    assert "secret_script" not in text
    assert "display: none" not in text
    assert "Не включать" not in text
