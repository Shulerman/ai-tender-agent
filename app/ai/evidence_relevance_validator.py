import json
import logging
import os
import re
import tempfile
import traceback

from app.ai.gemini import generate_text


logger = logging.getLogger(__name__)


VALID_STATUSES = {
    "Подтверждает",
    "Противоречит",
    "Недостаточно данных",
}


def collect_evidence(analysis) -> list[dict]:
    """Собирает все ожидающие проверки пары «утверждение — цитата»."""

    collected = []

    def append_items(id_prefix: str, evidence_items) -> None:
        for evidence_index, evidence in enumerate(evidence_items):
            if evidence.relevance_status != "Ожидает проверки":
                continue

            collected.append({
                "id": f"{id_prefix}-{evidence_index}",
                "claim": evidence.claim,
                "quote": evidence.quote,
                "evidence_object": evidence,
            })

    for product_index, product in enumerate(analysis.products):
        append_items(f"product-{product_index}", product.evidence)

        for attribute_index, attribute in enumerate(product.attributes):
            append_items(
                f"product-attribute-{product_index}-{attribute_index}",
                attribute.evidence,
            )

    sections = (
        ("technical", analysis.technical_requirements),
        ("delivery", analysis.delivery_requirements),
        ("document", analysis.document_requirements),
        ("risk", analysis.risks_and_uncertainties),
    )

    for section_name, section in sections:
        for item_index, item in enumerate(section):
            append_items(f"{section_name}-{item_index}", item.evidence)

    return collected


def _mark_check_failed(collected: list[dict], explanation: str) -> None:
    for item in collected:
        evidence = item["evidence_object"]
        evidence.relevance_status = "Проверка не выполнена"
        evidence.relevance_explanation = explanation


def _save_validation_error(error: Exception) -> str:
    """Сохраняет traceback без промпта, документа, локальных данных и секретов."""

    diagnostic = traceback.format_exception(
        type(error),
        error,
        error.__traceback__,
    )
    message = "".join(diagnostic)

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")

    message = re.sub(
        r"(?i)([?&]key=)[^&\s]+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)(Bearer\s+)[^\s]+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)(x-goog-api-key[\"'=:\s]+)[^,\s'\"]+",
        r"\1[REDACTED]",
        message,
    )

    diagnostic_text = (
        "Gemini semantic evidence validation failure\n"
        f"Exception type: {type(error).__name__}\n"
        "Traceback and exception chain:\n"
        f"{message[-12000:]}\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".txt",
        prefix="gemini_evidence_validation_error_",
        delete=False,
    ) as file:
        file.write(diagnostic_text)
        return file.name


async def validate_evidence_relevance(analysis) -> None:
    """
    Проверяет смысловое соответствие цитат утверждениям одним запросом Gemini.

    Ошибка проверки не прерывает технический анализ: все затронутые
    доказательства получают безопасный статус «Проверка не выполнена».
    """

    collected = collect_evidence(analysis)
    if not collected:
        return

    request_items = [
        {
            "id": item["id"],
            "claim": item["claim"],
            "quote": item["quote"],
        }
        for item in collected
    ]

    prompt = f"""
Ты — независимый проверяющий доказательств в документации закупок.

Твоя задача — проверить, подтверждает ли приведённая цитата
конкретное утверждение.

Для каждой пары «утверждение — цитата» выбери ровно один статус:

1. «Подтверждает» — цитата прямо и однозначно подтверждает
   утверждение. Все существенные числа, сроки, условия
   и характеристики совпадают.

2. «Противоречит» — цитата содержит сведения, которые
   прямо противоречат утверждению.

3. «Недостаточно данных» — цитата не позволяет уверенно
   подтвердить или опровергнуть утверждение, подтверждает
   только его часть либо требует дополнительного контекста.

ВАЖНЫЕ ПРАВИЛА:

- Не доверяй утверждению только потому, что оно сформулировано уверенно.
- Проверяй числа, даты, единицы измерения и условия особенно внимательно.
- Не додумывай отсутствующую информацию.
- Не используй внешние знания.
- Оценивай только предоставленную пару.
- Не считай тематическое сходство доказательством.
- Если цитата подтверждает только часть утверждения,
  выбирай «Недостаточно данных».
- Не изменяй идентификаторы.
- Для каждой пары обязательно верни объяснение.
- Не пропускай ни одну пару.

Верни только JSON следующей структуры:

{{
  "results": [
    {{
      "id": "идентификатор из входных данных",
      "status": "Подтверждает",
      "explanation": "Краткое объяснение результата"
    }}
  ]
}}

ДАННЫЕ ДЛЯ ПРОВЕРКИ:

{json.dumps(request_items, ensure_ascii=False)}
"""

    try:
        response = await generate_text(prompt, json_mode=True)
        if not isinstance(response, str):
            raise ValueError("Ответ Gemini должен быть строкой")

        response = response.strip()

        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]

        if response.endswith("```"):
            response = response[:-3]

        parsed = json.loads(response.strip())

        if not isinstance(parsed, dict):
            raise ValueError("Ответ должен быть JSON-объектом")

        results = parsed.get("results")
        if not isinstance(results, list):
            raise ValueError("В ответе отсутствует список results")

    except Exception as error:
        try:
            diagnostic_path = _save_validation_error(error)
            logger.warning(
                "Смысловая проверка доказательств не выполнена "
                "(%s); diagnostic=%s",
                type(error).__name__,
                diagnostic_path,
            )
        except OSError:
            logger.warning(
                "Смысловая проверка доказательств не выполнена (%s); "
                "диагностический файл создать не удалось",
                type(error).__name__,
            )

        _mark_check_failed(
            collected,
            "Не удалось получить или разобрать результат смысловой проверки.",
        )
        return

    expected_ids = {
        item["id"]: item["evidence_object"]
        for item in collected
    }
    received_ids = set()

    for result in results:
        if not isinstance(result, dict):
            continue

        evidence_id = result.get("id")
        if not isinstance(evidence_id, str) or evidence_id not in expected_ids:
            continue

        if evidence_id in received_ids:
            continue

        received_ids.add(evidence_id)
        evidence = expected_ids[evidence_id]
        status = result.get("status")
        explanation = result.get("explanation")

        if (
            not isinstance(status, str)
            or status not in VALID_STATUSES
            or not isinstance(explanation, str)
            or not explanation.strip()
        ):
            evidence.relevance_status = "Проверка не выполнена"
            evidence.relevance_explanation = (
                "Gemini вернул некорректный результат проверки."
            )
            continue

        evidence.relevance_status = status
        evidence.relevance_explanation = explanation.strip()

    for evidence_id, evidence in expected_ids.items():
        if evidence_id not in received_ids:
            evidence.relevance_status = "Проверка не выполнена"
            evidence.relevance_explanation = (
                "Gemini не вернул результат для этой пары."
            )
