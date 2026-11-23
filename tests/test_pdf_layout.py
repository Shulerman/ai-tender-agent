from app.documents.pdf_layout import detect_table_regions


class FakePage:
    def __init__(self, rows):
        self.rows = rows

    def extract_words(self, **kwargs):
        words = []
        for top, cells in self.rows:
            for x, text in cells:
                words.append({
                    "text": text,
                    "x0": float(x),
                    "x1": float(x) + 20,
                    "top": float(top),
                    "bottom": float(top) + 10,
                })
        return words


def test_detects_repeated_table_rows_and_preserves_continuation():
    page = FakePage([
        (100, [(90, "Артикул"), (161, "Название"), (265, "Количество"),
               (344, "Единица"), (416, "Требование")]),
        (125, [(90, "P-001"), (161, "Насос"), (265, "4"),
               (344, "шт"), (416, "Производительность")]),
        (140, [(161, "не менее"), (416, "12 м3/ч")]),
        (165, [(90, "P-002"), (161, "Двигатель"), (265, "2"),
               (344, "шт"), (416, "Мощность")]),
        (190, [(90, "P-003"), (161, "Подшипник"),
               (344, "шт"), (416, "Тип 6205")]),
        (230, [(90, "Условия поставки"), (120, "Срок поставки")]),
    ])

    regions = detect_table_regions(page)

    assert len(regions) == 1
    region = regions[0]

    assert len(region["lines"]) == 5
    assert "не менее 12 м3/ч" in region["lines"][2]["text"]
    assert "P-003" in region["lines"][4]["text"]
    assert len(region["lines"][4]["anchor_hits"]) >= 3


def test_ignores_ordinary_paragraphs_with_unstable_word_positions():
    page = FakePage([
        (100, [(90, "Срок"), (120, "поставки"), (180, "составляет")]),
        (125, [(90, "не позднее"), (145, "двадцати"), (210, "дней")]),
        (150, [(90, "Адрес"), (130, "поставки"), (190, "Москва")]),
        (175, [(90, "Документы"), (160, "передаются"), (240, "вместе")]),
    ])

    assert detect_table_regions(page) == []


def test_detects_long_table_continuation_on_next_page():
    page = FakePage([
        (74, [(90, "Параметр"), (141, "13"), (234, "Значение"),
              (284, "13"), (378, "справочно")]),
        (99, [(90, "Параметр"), (141, "14"), (234, "Значение"),
              (284, "14"), (378, "справочно")]),
        (124, [(90, "Параметр"), (141, "15"), (234, "Значение"),
               (284, "15"), (378, "обязательно")]),
        (149, [(90, "Параметр"), (141, "16"), (234, "Значение"),
               (284, "16"), (378, "справочно")]),
        (190, [(90, "Условия"), (130, "поставки")]),
    ])

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0]["lines"]) == 4
    assert len(regions[0]["anchors"]) == 5


def test_separates_two_tables_with_different_column_profiles():
    page = FakePage([
        (100, [(90, "Артикул"), (161, "Название"), (265, "Количество"),
               (344, "Единица"), (416, "Требование")]),
        (125, [(90, "P-001"), (161, "Насос"), (265, "4"),
               (344, "шт"), (416, "Мощность")]),
        (150, [(90, "P-002"), (161, "Мотор"), (265, "2"),
               (344, "шт"), (416, "Напряжение")]),
        (200, [(90, "Параметр"), (234, "Значение"), (378, "Статус")]),
        (225, [(90, "Параметр"), (141, "01"), (234, "Значение"),
               (284, "01"), (378, "обязательно")]),
        (250, [(90, "Параметр"), (141, "02"), (234, "Значение"),
               (284, "02"), (378, "справочно")]),
        (275, [(90, "Параметр"), (141, "03"), (234, "Значение"),
               (284, "03"), (378, "обязательно")]),
    ])

    regions = detect_table_regions(page)

    assert len(regions) == 2
    assert "P-001" in regions[0]["lines"][1]["text"]
    assert "Параметр 01" in regions[1]["lines"][1]["text"]


def test_real_tender_pdf_has_two_separate_tables_on_first_page():
    import pdfplumber

    with pdfplumber.open("tests/tender_audit.pdf") as pdf:
        regions = detect_table_regions(pdf.pages[0])

    assert len(regions) == 2
    assert len(regions[0]["lines"]) == 7
    assert len(regions[1]["lines"]) == 13
    assert "P-003" in " ".join(
        line["text"] for line in regions[0]["lines"]
    )


def test_real_tender_pdf_excludes_delivery_paragraphs():
    import pdfplumber

    with pdfplumber.open("tests/tender_audit.pdf") as pdf:
        regions = detect_table_regions(pdf.pages[1])

    assert len(regions) == 1
    combined = " ".join(line["text"] for line in regions[0]["lines"])
    assert "Параметр 30" in combined
    assert "Условия поставки" not in combined
    assert "Адрес поставки" not in combined


def test_real_edge_pdf_has_no_false_table_regions():
    import pdfplumber

    with pdfplumber.open("tests/edge.pdf") as pdf:
        for page in pdf.pages:
            assert detect_table_regions(page) == []
