import json

from app.ai.gemini import generate_text


VALID_STATUSES = {
    "Подтверждает",
    "Противоречит",
    "Недостаточно данных",
}


def collect_evidence(analysis) -> list[dict]:
    """
    Собирает все пары «утверждение — цитата»
    для смысловой проверки.
    """

    sections = [
        ("product", analysis.products),
        ("delivery", analysis.delivery_requirements),
        ("document", analysis.document_requirements),
        ("risk", analysis.risks_and_uncertainties),
    ]

    collected = []

    for section_name, section in sections:
        for item_index, item in enumerate(section):
            for evidence_index, evidence in enumerate(item.evidence):

                if evidence.relevance_status != "Ожидает проверки":
                    continue

                collected.append({
                    "id": (
                        f"{section_name}-"
                        f"{item_index}-"
                        f"{evidence_index}"
                    ),
                    "claim": evidence.claim,
                    "quote": evidence.quote,
                    "evidence_object": evidence,
                })

    return collected


async def validate_evidence_relevance(analysis) -> None:
    """
    Проверяет, подтверждает ли цитата конкретное утверждение.

    Проверка выполняется одним пакетным запросом Gemini.
    Если проверка не удалась, результат не считается подтверждённым.
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
        response = response.strip()

        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]

        if response.endswith("```"):
            response = response[:-3]

        parsed = json.loads(response)

        if not isinstance(parsed, dict):
            raise ValueError("Ответ должен быть JSON-объектом")

        results = parsed.get("results")

        if not isinstance(results, list):
            raise ValueError("В ответе отсутствует список results")

    except (RuntimeError, ValueError, json.JSONDecodeError):
        for item in collected:
            item["evidence_object"].relevance_status = (
                "Проверка не выполнена"
            )
            item["evidence_object"].relevance_explanation = (
                "Не удалось получить или разобрать результат "
                "смысловой проверки."
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

        if evidence_id not in expected_ids:
            continue

        if evidence_id in received_ids:
            continue

        received_ids.add(evidence_id)

        status = result.get("status")
        explanation = result.get("explanation")

        evidence = expected_ids[evidence_id]

        if (
            status not in VALID_STATUSES
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
