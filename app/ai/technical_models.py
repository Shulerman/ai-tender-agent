from pydantic import BaseModel, Field, model_validator

NOT_SPECIFIED = "Не указано"
EVIDENCE_NOT_CHECKED = "Не проверено"


class Evidence(BaseModel):
    claim: str
    quote: str
    relevance_status: str = EVIDENCE_NOT_CHECKED
    relevance_explanation: str = ""


class ProductAttribute(BaseModel):
    """Одна извлечённая техническая характеристика товара."""

    name: str
    value: str
    unit: str | None = None
    operator: str | None = None
    is_required: bool | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class ProductAnalysis(BaseModel):
    name: str
    quantity: str
    unit: str
    technical_characteristics: str = NOT_SPECIFIED
    packaging_requirements: str = NOT_SPECIFIED
    quality_and_standards: str = NOT_SPECIFIED
    attributes: list[ProductAttribute] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_status: str = EVIDENCE_NOT_CHECKED
    rejected_quotes: list[str] = Field(default_factory=list)


class DeliveryRequirement(BaseModel):
    delivery_time: str = NOT_SPECIFIED
    delivery_address: str = NOT_SPECIFIED
    quotes: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_status: str = EVIDENCE_NOT_CHECKED
    rejected_quotes: list[str] = Field(default_factory=list)


class DocumentRequirement(BaseModel):
    requirement_type: str
    quotes: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_status: str = EVIDENCE_NOT_CHECKED
    rejected_quotes: list[str] = Field(default_factory=list)

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
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_status: str = EVIDENCE_NOT_CHECKED
    rejected_quotes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_risk(cls, value):
        if isinstance(value, str):
            return {
                "description": value,
                "quotes": [],
            }
        return value


class TechnicalAnalysis(BaseModel):
    products: list[ProductAnalysis]
    delivery_requirements: list[DeliveryRequirement]
    document_requirements: list[DocumentRequirement]
    risks_and_uncertainties: list[Risk]
    questions_to_customer: list[str]
