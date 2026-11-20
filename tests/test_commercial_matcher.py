from app.commercial.matcher import compare_product_to_requirement


def test_full_match():
    result = compare_product_to_requirement(
        [
            {"name": "diameter", "value": 10, "unit": "mm"},
            {"name": "material", "value": "steel"},
        ],
        {
            "diameter": {"value": 10, "unit": "mm"},
            "material": "steel",
        },
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0
    assert len(result["confirmed_characteristics"]) == 2
    assert result["missing_characteristics"] == []
    assert result["discrepancies"] == []


def test_potential_analogue_with_missing_characteristic():
    result = compare_product_to_requirement(
        [
            {"name": "diameter", "value": 10, "unit": "mm"},
            {"name": "material", "value": "steel"},
        ],
        {
            "diameter": {"value": 10, "unit": "mm"},
        },
    )

    assert result["match_status"] == "Потенциальный аналог"
    assert result["match_score"] == 50.0
    assert len(result["confirmed_characteristics"]) == 1
    assert len(result["missing_characteristics"]) == 1
    assert result["is_candidate"] is True


def test_potential_analogue_with_numeric_discrepancy():
    result = compare_product_to_requirement(
        [
            {"name": "diameter", "value": 10, "unit": "mm"},
            {"name": "material", "value": "steel"},
        ],
        {
            "diameter": {"value": 12, "unit": "mm"},
            "material": "steel",
        },
    )

    assert result["match_status"] == "Потенциальный аналог"
    assert result["match_score"] == 50.0
    assert len(result["discrepancies"]) == 1
    assert result["discrepancies"][0]["actual_value"] == 12


def test_different_units_are_not_automatically_converted():
    result = compare_product_to_requirement(
        [{"name": "diameter", "value": 10, "unit": "mm"}],
        {"diameter": {"value": 1, "unit": "cm"}},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["confirmed_characteristics"] == []
    assert len(result["missing_characteristics"]) == 1


def test_numeric_minimum_operator():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": "kg", "operator": ">="}],
        {"capacity": {"value": 120, "unit": "kg"}},
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0


def test_no_confirmed_characteristics_is_not_a_candidate():
    result = compare_product_to_requirement(
        [{"name": "material", "value": "steel"}],
        {"material": "unknown"},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False
    assert result["match_score"] == 0.0


def test_optional_requirement_attribute_is_not_required_for_full_match():
    result = compare_product_to_requirement(
        [
            {"name": "material", "value": "steel"},
            {"name": "color", "value": "black", "is_required": False},
        ],
        {"material": "steel"},
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0
