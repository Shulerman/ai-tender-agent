from app.documents.pdf_reader import _reconstruct_table_rows


def _row(number, *cells):
    return {
        "row_number": number,
        "cells": list(cells),
        "cell_data": [],
    }


def test_reconstructs_wrapped_product_rows_and_preserves_empty_quantity():
    rows = [
        _row(1, "Артикул", "Наименование", "Количество", "Единица", "Требование"),
        _row(2, "P-001", "Промышленный", "4", "шт.", "Производительность"),
        _row(3, "", "насос", "", "", "не менее 12 м³/ч"),
        _row(4, "P-002", "Электродвигатель", "2", "шт.", "Мощность не менее"),
        _row(5, "", "", "", "", "5,5 кВт"),
        _row(6, "P-003", "Подшипник", "", "шт.", "Тип 6205, закрытый"),
    ]

    result = _reconstruct_table_rows(rows)

    assert len(result) == 4
    assert result[1]["cells"] == [
        "P-001", "Промышленный насос", "4", "шт.",
        "Производительность не менее 12 м³/ч",
    ]
    assert result[1]["source_rows"][0]["row_number"] == 2
    assert result[1]["source_rows"][1]["row_number"] == 3
    assert result[2]["cells"] == [
        "P-002", "Электродвигатель", "2", "шт.", "Мощность не менее 5,5 кВт",
    ]
    assert result[3]["cells"][2] == ""


def test_does_not_merge_header_or_independent_product_rows():
    rows = [
        _row(1, "Артикул", "Наименование"),
        _row(2, "P-001", "Насос"),
        _row(3, "P-002", "Двигатель"),
    ]

    result = _reconstruct_table_rows(rows)

    assert len(result) == 3
    assert all(len(item["source_rows"]) == 1 for item in result)
