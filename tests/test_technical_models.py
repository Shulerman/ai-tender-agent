import pytest
from pydantic import ValidationError

from app.ai.technical_models import Evidence, ProductAnalysis, ProductAttribute


def test_product_analysis_keeps_backward_compatibility():
    product = ProductAnalysis(
        name="Тестовый товар",
        quantity="10",
        unit="шт.",
    )
    assert product.attributes == []


def test_product_attribute_preserves_unknown_comparison_details():
    attribute = ProductAttribute(
        name="Диаметр",
        value="не менее 20",
        unit="мм",
    )
    assert attribute.operator is None
    assert attribute.is_required is None
    assert attribute.evidence == []


def test_product_attribute_validates_and_keeps_its_evidence():
    attribute = ProductAttribute(
        name="Диаметр",
        value="20",
        unit="мм",
        operator=">=",
        is_required=True,
        evidence=[
            Evidence(
                claim="Диаметр не менее 20 мм",
                quote="Диаметр не менее 20 мм",
            )
        ],
    )
    product = ProductAnalysis(
        name="Тестовый товар",
        quantity="10",
        unit="шт.",
        attributes=[attribute],
    )
    dumped = product.model_dump()
    assert dumped["attributes"][0]["name"] == "Диаметр"
    assert dumped["attributes"][0]["operator"] == ">="
    assert dumped["attributes"][0]["evidence"][0]["quote"] == (
        "Диаметр не менее 20 мм"
    )


def test_product_attribute_requires_name_and_value():
    with pytest.raises(ValidationError):
        ProductAttribute(name="Диаметр")
