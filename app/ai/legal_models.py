from pydantic import BaseModel, Field, model_validator


def normalize_text(value):
    """Преобразует строку или объект Gemini в обычный текст."""

    if isinstance(value, str):
        return value.strip() or "Не указано"

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

    # Юридическая оценка
    risk_level: str = "Не определён"

    # Коммерческая оценка для поставщика
    commercial_risk_level: str = "Недостаточно информации"
    commercial_risk_reason: str = "Не оценено"

    document_clause: str = "Не указано"
    document_quote: str = "Не указано"

    # Правовое основание
    legal_basis: str = "Не проверено"
    legal_basis_status: str = "Требует проверки"
    legal_basis_text: str = "Не найдено"

    # Проверка применимости правовой нормы
    legal_applicability_status: str = "Требует проверки"
    legal_applicability_reason: str = "Не проверено"
    legal_applicability_evidence: str = "Не найдено"

    # Отдельная проверка наличия нарушения закона
    legal_violation_status: str = "Требует проверки"
    legal_violation_reason: str = "Не проверено"
    legal_violation_evidence: str = "Не найдено"

    recommendation: str = "Требуется проверка специалистом"

    @model_validator(mode="before")
    @classmethod
    def normalize_issue(cls, value):
        if isinstance(value, str):
            return {
                "category": "Юридический вопрос",
                "description": value,
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

        for field in [
            "commercial_risk_reason",
            "legal_basis",
            "legal_basis_status",
            "legal_basis_text",
            "legal_applicability_status",
            "legal_applicability_reason",
            "legal_applicability_evidence",
            "legal_violation_status",
            "legal_violation_reason",
            "legal_violation_evidence",
        ]:
            if field in data:
                data[field] = normalize_text(data[field])

        return data


class CommercialRisk(BaseModel):
    category: str = "Коммерческий риск"
    description: str = "Не указано"

    commercial_risk_level: str = "Недостаточно информации"
    commercial_risk_reason: str = "Не оценено"

    document_clause: str = "Не указано"
    document_quote: str = "Не указано"

    recommendation: str = "Требуется дополнительная оценка"

    @model_validator(mode="before")
    @classmethod
    def normalize_commercial_risk(cls, value):
        if isinstance(value, str):
            return {
                "category": "Коммерческий риск",
                "description": value,
            }

        if not isinstance(value, dict):
            return value

        data = dict(value)

        if "description" not in data:
            data["description"] = (
                data.get("risk_description")
                or data.get("details")
                or data.get("explanation")
                or data.get("value")
                or "Не указано"
            )

        for field in [
            "category",
            "description",
            "commercial_risk_level",
            "commercial_risk_reason",
            "document_clause",
            "document_quote",
            "recommendation",
        ]:
            if field in data:
                data[field] = normalize_text(data[field])

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

    commercial_risks: list[CommercialRisk] = Field(
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
