
from pydantic import BaseModel, Field, model_validator


class ProductAnalysis(BaseModel):
    name: str
    quantity: str
    unit: str
    technical_characteristics: str = "Не указано"
    packaging_requirements: str = "Не указано"
    quality_and_standards: str = "Не указано"
    quotes: list[str] = Field(default_factory=list)


class DeliveryRequirement(BaseModel):
    delivery_time: str = "Не указано"
    delivery_address: str = "Не указано"
    quotes: list[str] = Field(default_factory=list)


class DocumentRequirement(BaseModel):
    requirement_type: str
    quotes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_requirement(cls, value):
        if isinstance(value, dict):
            value = value.copy()

            if "requirement_type" not in value and "requirement" in value:
                value["requirement_type"] = value.pop("requirement")

        return value


class Risk(BaseModel):
    description: str
    quotes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_risk(cls, value):
        if isinstance(value, str):
            return {
                "description": value,
                "quotes": []
            }

        return value


class TechnicalAnalysis(BaseModel):
    products: list[ProductAnalysis]
    delivery_requirements: list[DeliveryRequirement]
    document_requirements: list[DocumentRequirement]
    risks_and_uncertainties: list[Risk]
    questions_to_customer: list[str]
