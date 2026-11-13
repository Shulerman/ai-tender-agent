
from pydantic import BaseModel, Field, model_validator


def normalize_text(value):
    """Преобразует строку или объект Gemini в обычный текст."""

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        preferred_keys = [
            "description",
            "question",
            "risk_assessment",
            "summary",
            "details",
            "explanation",
            "text",
            "value",
        ]

        parts = []

        for key in preferred_keys:
            item = value.get(key)

            if isinstance(item, str) and item.strip():
                parts.append(item.strip())

        if parts:
            return " ".join(parts)

        return "; ".join(
            f"{key}: {item}"
            for key, item in value.items()
            if isinstance(item, (str, int, float))
        )

    if value is None:
        return "Не указано"

    return str(value)


class LegalIssue(BaseModel):
    category: str = "Юридический вопрос"
    description: str = "Не указано"
    risk_level: str = "Не определён"
    document_clause: str = "Не указано"
    document_quote: str = "Не указано"
    legal_basis: str = "Не проверено"
    legal_basis_status: str = "Требует проверки"
    recommendation: str = "Требуется проверка специалистом"

    @model_validator(mode="before")
    @classmethod
    def normalize_issue(cls, value):
        if isinstance(value, str):
            return {
                "category": "Юридический риск",
                "description": value
            }

        if not isinstance(value, dict):
            return value

        data = dict(value)

        if "category" not in data:
            data["category"] = (
                data.get("term_name")
                or data.get("issue_type")
                or data.get("risk_type")
                or "Юридический вопрос"
            )

        if "description" not in data:
            description = (
                data.get("term_description")
                or data.get("risk_description")
                or data.get("details")
                or data.get("explanation")
                or data.get("requirement")
                or data.get("term_value")
                or data.get("value")
                or data.get("analysis")
                or data.get("term_name")
                or "Не указано"
            )

            data["description"] = normalize_text(description)

        else:
            data["description"] = normalize_text(
                data["description"]
            )

        return data


class LegalAnalysis(BaseModel):
    procurement_law: str = "Не определено"
    procurement_type: str = "Не определено"

    contract_terms: list[LegalIssue] = Field(
        default_factory=list
    )

    risks: list[LegalIssue] = Field(
        default_factory=list
    )

    contradictions: list[LegalIssue] = Field(
        default_factory=list
    )

    missing_information: list[str] = Field(
        default_factory=list
    )

    questions_to_customer: list[str] = Field(
        default_factory=list
    )

    overall_conclusion: str = "Не сформировано"

    @model_validator(mode="before")
    @classmethod
    def normalize_analysis(cls, value):
        if not isinstance(value, dict):
            return value

        data = dict(value)

        for field in [
            "missing_information",
            "questions_to_customer",
        ]:
            items = data.get(field, [])

            if isinstance(items, str):
                items = [items]

            if isinstance(items, list):
                data[field] = [
                    normalize_text(item)
                    for item in items
                ]

        data["overall_conclusion"] = normalize_text(
            data.get("overall_conclusion", "Не сформировано")
        )

        return data
