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


def test_equivalent_standard_units_are_converted():
    result = compare_product_to_requirement(
        [{"name": "diameter", "value": 10, "unit": "mm"}],
        {"diameter": {"value": 1, "unit": "cm"}},
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["is_candidate"] is True
    assert result["match_score"] == 100.0
    assert len(result["confirmed_characteristics"]) == 1


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

def test_ambiguous_normalized_product_attribute_names_are_not_matched():
    result = compare_product_to_requirement(
        [{"name": "max pressure", "value": 10, "unit": "bar"}],
        {
            "max-pressure": {"value": 10, "unit": "bar"},
            "max_pressure": {"value": 20, "unit": "bar"},
        },
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False
    assert result["confirmed_characteristics"] == []
    assert "неоднозначные" in result["missing_characteristics"][0]["reason"]


def test_invalid_requirement_names_do_not_distort_match_score():
    result = compare_product_to_requirement(
        [
            {"name": "", "value": 10},
            {"name": None, "value": 20},
            {"name": "material", "value": "steel"},
        ],
        {"material": "steel"},
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0
    assert len(result["confirmed_characteristics"]) == 1


def test_non_finite_expected_number_is_not_a_match():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": "NaN", "unit": "kg"}],
        {"capacity": {"value": "NaN", "unit": "kg"}},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False


def test_non_finite_actual_number_is_not_a_match():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": "kg"}],
        {"capacity": {"value": "Infinity", "unit": "kg"}},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False


def test_invalid_operator_type_does_not_raise():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": "kg", "operator": 5}],
        {"capacity": {"value": 100, "unit": "kg"}},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False

def test_invalid_unit_types_are_not_matched():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": 5}],
        {"capacity": {"value": 100, "unit": 5}},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False


def test_blank_and_missing_units_are_treated_equally():
    result = compare_product_to_requirement(
        [{"name": "material", "value": "steel", "unit": "   "}],
        {"material": {"value": "steel", "unit": None}},
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0


def test_unit_comparison_is_case_insensitive_and_trims_outer_spaces():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": " KG "}],
        {"capacity": {"value": 100, "unit": "kg"}},
    )

    assert result["match_status"] == "Полное соответствие"


def test_all_supported_numeric_operators_and_boundaries():
    cases = [
        (">", 11, True),
        (">", 10, False),
        (">=", 10, True),
        (">=", 9, False),
        ("<", 9, True),
        ("<", 10, False),
        ("<=", 10, True),
        ("<=", 11, False),
        ("=", 10, True),
        ("==", 10, True),
    ]

    for operator, actual, expected_match in cases:
        result = compare_product_to_requirement(
            [{
                "name": "capacity",
                "value": 10,
                "unit": "kg",
                "operator": operator,
            }],
            {"capacity": {"value": actual, "unit": "kg"}},
        )

        if expected_match:
            assert result["match_status"] == "Полное соответствие", (
                operator, actual, result
            )
            assert len(result["confirmed_characteristics"]) == 1
        else:
            assert len(result["discrepancies"]) == 1, (
                operator, actual, result
            )


def test_numeric_comparison_accepts_decimal_comma():
    result = compare_product_to_requirement(
        [{"name": "diameter", "value": "1,25", "unit": "mm"}],
        {"diameter": {"value": "1.25", "unit": "mm"}},
    )

    assert result["match_status"] == "Полное соответствие"


def test_operator_whitespace_is_normalized():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": "kg", "operator": " >= "}],
        {"capacity": {"value": 100, "unit": "kg"}},
    )

    assert result["match_status"] == "Полное соответствие"


def test_unknown_operator_is_not_treated_as_equality():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 100, "unit": "kg", "operator": "~="}],
        {"capacity": {"value": 100, "unit": "kg"}},
    )

    assert result["match_status"] == "Недостаточно данных"
    assert result["is_candidate"] is False

def test_empty_values_are_not_confirmed_as_matching():
    for value in ("", " ", "   "):
        result = compare_product_to_requirement(
            [{"name": "material", "value": value}],
            {"material": value},
        )
        assert result["is_candidate"] is False
        assert result["match_status"] == "Недостаточно данных"


def test_malformed_numeric_strings_are_not_confirmed_by_text_equality():
    for value in ("1,234.56", "1.234,56", "10.5.6"):
        result = compare_product_to_requirement(
            [{"name": "capacity", "value": value, "unit": "kg"}],
            {"capacity": {"value": value, "unit": "kg"}},
        )
        assert result["is_candidate"] is False
        assert result["match_status"] == "Недостаточно данных"


def test_valid_decimal_comma_values_still_match():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": "10,5", "unit": "kg"}],
        {"capacity": {"value": "10.5", "unit": "kg"}},
    )
    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0

def test_identical_lists_are_not_confirmed_as_matching():
    result = compare_product_to_requirement(
        [{"name": "materials", "value": ["steel", "aluminum"]}],
        {"materials": ["steel", "aluminum"]},
    )
    assert result["is_candidate"] is False
    assert result["match_status"] == "Недостаточно данных"
    assert len(result["missing_characteristics"]) == 1
    assert result["discrepancies"] == []


def test_identical_nested_dictionaries_are_not_confirmed_as_matching():
    value = {"grade": "A", "code": 10}
    result = compare_product_to_requirement(
        [{"name": "specification", "value": value}],
        {"specification": {"value": value}},
    )
    assert result["is_candidate"] is False
    assert result["match_status"] == "Недостаточно данных"
    assert len(result["missing_characteristics"]) == 1
    assert result["discrepancies"] == []


def test_matching_boolean_values_are_supported():
    for value in (True, False):
        result = compare_product_to_requirement(
            [{"name": "certified", "value": value}],
            {"certified": value},
        )
        assert result["match_status"] == "Полное соответствие"
        assert result["is_candidate"] is True
        assert len(result["confirmed_characteristics"]) == 1


def test_boolean_does_not_match_string_or_number():
    for actual in ("True", 1, 0):
        result = compare_product_to_requirement(
            [{"name": "certified", "value": True}],
            {"certified": actual},
        )
        assert result["is_candidate"] is False
        assert result["match_status"] == "Недостаточно данных"
        assert len(result["missing_characteristics"]) == 1
        assert result["discrepancies"] == []


def test_numeric_string_and_number_still_match():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 10}],
        {"capacity": "10"},
    )
    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0


def test_standard_mass_units_are_converted():
    result = compare_product_to_requirement(
        [{"name": "weight", "value": 1, "unit": "kg"}],
        {"weight": {"value": 1000, "unit": "g"}},
    )

    assert result["match_status"] == "Полное соответствие"
    assert result["match_score"] == 100.0
    assert len(result["confirmed_characteristics"]) == 1


def test_numeric_operator_works_after_unit_conversion():
    result = compare_product_to_requirement(
        [{
            "name": "diameter",
            "value": 10,
            "unit": "mm",
            "operator": ">=",
        }],
        {"diameter": {"value": 1.1, "unit": "cm"}},
    )

    assert result["match_status"] == "Полное соответствие"


def test_units_from_different_families_are_not_converted():
    result = compare_product_to_requirement(
        [{"name": "capacity", "value": 10, "unit": "kg"}],
        {"capacity": {"value": 10, "unit": "mm"}},
    )

    assert result["is_candidate"] is False
    assert result["match_status"] == "Недостаточно данных"


def test_explicit_characteristic_synonyms_are_matched():
    result = compare_product_to_requirement(
        [{"name": "диаметр", "value": 10, "unit": "mm"}],
        {"Ø": {"value": 10, "unit": "mm"}},
    )

    assert result["match_status"] == "Полное соответствие"


def test_outer_and_inner_diameters_are_not_synonyms():
    result = compare_product_to_requirement(
        [{"name": "внутренний диаметр", "value": 10, "unit": "mm"}],
        {"наружный диаметр": {"value": 10, "unit": "mm"}},
    )

    assert result["is_candidate"] is False
    assert result["match_status"] == "Недостаточно данных"


def test_synonym_collision_remains_ambiguous():
    result = compare_product_to_requirement(
        [{"name": "диаметр", "value": 10, "unit": "mm"}],
        {
            "diameter": {"value": 10, "unit": "mm"},
            "Ø": {"value": 10, "unit": "mm"},
        },
    )

    assert result["is_candidate"] is False
    assert result["confirmed_characteristics"] == []
    assert "неоднозначные" in result["missing_characteristics"][0]["reason"]
