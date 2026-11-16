from app.ai.evidence_validator import validate_quotes


def test_exact_quote_is_accepted():
    document = "Поставка товара осуществляется в течение 10 дней."

    result = validate_quotes(
        ["Поставка товара осуществляется в течение 10 дней."],
        document,
    )

    assert result["accepted"] == [
        "Поставка товара осуществляется в течение 10 дней."
    ]
    assert result["rejected"] == []
    assert result["is_valid"] is True


def test_quote_with_different_whitespace_is_accepted():
    document = "Поставка товара осуществляется\nв течение   10 дней."

    result = validate_quotes(
        ["Поставка товара осуществляется в течение 10 дней."],
        document,
    )

    assert len(result["accepted"]) == 1
    assert result["rejected"] == []
    assert result["is_valid"] is True


def test_fabricated_quote_is_rejected():
    document = "Поставка товара осуществляется в течение 10 дней."

    result = validate_quotes(
        ["Поставка товара осуществляется в течение 5 дней."],
        document,
    )

    assert result["accepted"] == []
    assert len(result["rejected"]) == 1
    assert result["is_valid"] is False


def test_mixed_quotes_are_separated():
    document = "Срок поставки — 10 дней."

    result = validate_quotes(
        [
            "Срок поставки — 10 дней.",
            "Срок поставки — 5 дней.",
        ],
        document,
    )

    assert len(result["accepted"]) == 1
    assert len(result["rejected"]) == 1
    assert result["is_valid"] is False


def test_empty_quote_is_rejected():
    document = "Текст документа."

    result = validate_quotes([""], document)

    assert result["accepted"] == []
    assert result["rejected"] == [""]
    assert result["is_valid"] is False
