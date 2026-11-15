import json
import re

from pydantic import ValidationError

from app.ai.gemini import generate_text
from app.ai.legal_models import LegalAnalysis
from app.database import SessionLocal
from app.legal_knowledge.service import (
    get_legal_provision,
    search_legal_provisions,
)


LEGAL_VERSION_IDS = {
    "44-ФЗ": "44-FZ-2026-10-01",
}

# Рабочая редакция принята как подтверждённая для разработки.
# Это временное проектное допущение, а не независимая проверка
# официального источника и актуальности законодательства.
LEGAL_VERSION_VERIFIED = {
    "44-ФЗ": True,
}


def detect_procurement_law(document_text: str) -> str:
    has_44_fz = bool(
        re.search(r"44\s*[-‑–—]?\s*ФЗ", document_text, re.IGNORECASE)
    )
    has_223_fz = bool(
        re.search(r"223\s*[-‑–—]?\s*ФЗ", document_text, re.IGNORECASE)
    )

    if has_44_fz and not has_223_fz:
        return "44-ФЗ"
    if has_223_fz and not has_44_fz:
        return "223-ФЗ"
    if has_44_fz and has_223_fz:
        return "Требуется дополнительная проверка"

    return "Не удалось определить"


def extract_procurement_type(document_text: str) -> str | None:
    """Извлекает предмет закупки из явно обозначенного поля документа."""

    patterns = [
        r"(?:предмет|объект)\s+закупки\s*[:\-—]\s*([^\n.;]+)",
        r"предметом\s+закупки\s+является\s+([^\n.;]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, document_text, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" \t\r\n\"'")

            if value:
                return value[0].upper() + value[1:]

    return None


def has_explicit_payment_deadline(document_text: str) -> bool:
    """Проверяет, указан ли конкретный срок оплаты в тексте документа."""

    sentences = re.split(r"(?<=[.!?])\s+|\n+", document_text)

    payment_pattern = re.compile(
        r"оплат\w*|расчет\w*|перечислени\w*",
        re.IGNORECASE,
    )

    deadline_patterns = [
        re.compile(
            r"(?:в\s+течение|не\s+позднее|срок\w*\s+оплат\w*\s*[:\-—]?)"
            r"\s*\d+\s*(?:рабочих|календарных)?\s*дн\w*",
            re.IGNORECASE,
        ),
        re.compile(
            r"\d+\s*[-–]?\s*(?:рабочих|календарных)?\s*дн\w*"
            r"\s*(?:с\s+даты|со\s+дня|после)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:в\s+)?\d+\s*[-–]\s*дневн\w*\s+срок",
            re.IGNORECASE,
        ),
        re.compile(
            r"срок\w*\s+оплат\w*\s+(?:составляет|установлен|определен)"
            r"\s*\d+\s*(?:рабочих|календарных)?\s*дн\w*",
            re.IGNORECASE,
        ),
    ]

    for sentence in sentences:
        if not payment_pattern.search(sentence):
            continue

        if any(pattern.search(sentence) for pattern in deadline_patterns):
            return True

    return False

def normalize_legal_text(text: str) -> str:
    """
    Нормализует текст статьи, сохраняя переносы строк.

    В импортированном тексте встречается разрыв номера части 1.1
    на три строки: 1 / 1 / .
    """

    text = text.replace("\xa0", " ").replace("\u202f", " ")

    text = re.sub(
        r"(?m)^\s*(\d+)\s*\n\s*(\d+)\s*\n\s*\.",
        r"\1.\2.",
        text,
    )

    text = re.sub(r"[ \t]+", " ", text)

    return text


def extract_article_structure(article_text: str) -> dict:
    """
    Извлекает номера частей и пунктов из структуры статьи.

    Проверка выполняется по заголовкам частей и пунктов,
    а не по любым цифрам в тексте. Это снижает риск принять
    упоминание другой статьи или закона за нужную часть.
    """

    normalized_text = normalize_legal_text(article_text)
    lines = normalized_text.splitlines()

    # Убираем заголовок вида «Статья 96. Название».
    if lines and re.match(r"^\s*Статья\s+\d+", lines[0], re.IGNORECASE):
        body = "\n".join(lines[1:])
    else:
        body = normalized_text

    part_pattern = re.compile(
        r"(?m)^\s*(\d+(?:\.\d+)?)\s*\."
    )

    point_pattern = re.compile(
        r"(?m)^\s*(\d+)\s*[)]"
    )

    part_matches = list(part_pattern.finditer(body))

    parts = {}
    for index, match in enumerate(part_matches):
        part_number = match.group(1)

        block_start = match.end()
        if index + 1 < len(part_matches):
            block_end = part_matches[index + 1].start()
        else:
            block_end = len(body)

        part_text = body[block_start:block_end]

        points = set(point_pattern.findall(part_text))

        parts[part_number] = {
            "text": part_text,
            "points": points,
        }

    return {
        "parts": parts,
        "text": body,
    }


def extract_legal_reference(legal_basis: str) -> dict:
    """Извлекает статью, часть и пункт из ссылки Gemini."""

    text = str(legal_basis or "")

    article_match = re.search(
        r"стать(?:я|и|е|ю)\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    part_match = re.search(
        r"част(?:ь|и|ью|ях|ям)\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    point_match = re.search(
        r"пункт(?:а|е|ом|ы|ов)?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    return {
        "article": article_match.group(1) if article_match else None,
        "part": part_match.group(1) if part_match else None,
        "point": point_match.group(1) if point_match else None,
    }


def validate_legal_basis(
    legal_basis: str,
    procurement_law: str,
    db,
    article_cache: dict,
) -> str:
    """
    Проверяет наличие статьи, части и пункта в локальной базе.

    Результат подтверждает только структуру правовой ссылки.
    Он не подтверждает применимость нормы к условию закупки
    и не является заключением о законности этого условия.
    """

    reference = extract_legal_reference(legal_basis)

    article_number = reference["article"]
    part_number = reference["part"]
    point_number = reference["point"]

    if not article_number:
        return "Требует проверки"

    version_id = LEGAL_VERSION_IDS.get(procurement_law)

    if not version_id:
        return "Требует проверки"

    cache_key = (version_id, article_number)

    if cache_key not in article_cache:
        article_cache[cache_key] = get_legal_provision(
            db=db,
            version_id=version_id,
            article_number=article_number,
        )

    article = article_cache[cache_key]

    if not article:
        return "Статья не найдена в локальной базе"

    if not part_number:
        return "Статья найдена"

    structure = extract_article_structure(article["text"])
    parts = structure["parts"]

    if part_number not in parts:
        return "Статья найдена, часть не найдена"

    if not point_number:
        return "Статья и часть найдены"

    points = parts[part_number]["points"]

    if point_number not in points:
        return "Статья и часть найдены, пункт не найден"

    return "Структура нормы найдена"


def extract_legal_basis_text(
    legal_basis: str,
    procurement_law: str,
    db,
    article_cache: dict,
) -> str:
    """Извлекает текст статьи, части или конкретного пункта закона."""

    reference = extract_legal_reference(legal_basis)

    article_number = reference["article"]
    part_number = reference["part"]
    point_number = reference["point"]

    if not article_number:
        return "Не найдено"

    version_id = LEGAL_VERSION_IDS.get(procurement_law)

    if not version_id:
        return "Не найдено"

    cache_key = (version_id, article_number)

    if cache_key not in article_cache:
        article_cache[cache_key] = get_legal_provision(
            db=db,
            version_id=version_id,
            article_number=article_number,
        )

    article = article_cache[cache_key]

    if not article:
        return "Не найдено"

    if not part_number:
        return article["text"].strip()

    structure = extract_article_structure(article["text"])
    part = structure["parts"].get(part_number)

    if not part:
        return "Не найдено"

    part_text = part["text"]

    if not point_number:
        return f"{part_number}. {part_text.strip()}"

    point_matches = list(
        re.finditer(r"(?m)^\s*(\d+)\s*[)]", part_text)
    )

    for index, match in enumerate(point_matches):
        if match.group(1) != point_number:
            continue

        start = match.start()

        if index + 1 < len(point_matches):
            end = point_matches[index + 1].start()
        else:
            end = len(part_text)

        return part_text[start:end].strip()

    return "Не найдено"

def validate_result_legal_references(
    result: dict,
    procurement_law: str,
) -> dict:
    """Проверяет правовые основания во всех разделах анализа."""

    db = SessionLocal()
    article_cache = {}

    try:
        for collection_name in (
            "contract_terms",
            "risks",
            "contradictions",
        ):
            items = result.get(collection_name, [])

            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                legal_basis = item.get("legal_basis", "")

                if (
                    not legal_basis
                    or str(legal_basis).strip() in (
                        "Не указано",
                        "Не проверено",
                    )
                ):
                    item["legal_basis_status"] = "Требует проверки"
                    item["legal_basis_text"] = "Не найдено"
                    continue

                item["legal_basis_status"] = validate_legal_basis(
                    legal_basis=str(legal_basis),
                    procurement_law=procurement_law,
                    db=db,
                    article_cache=article_cache,
                )

                item["legal_basis_text"] = extract_legal_basis_text(
                    legal_basis=str(legal_basis),
                    procurement_law=procurement_law,
                    db=db,
                    article_cache=article_cache,
                )
    finally:
        db.close()

    return result




async def check_legal_applicability(result: dict) -> dict:
    """
    Пакетно проверяет применимость правовых норм и наличие
    фактического нарушения закона.

    При ошибке Gemini анализ закупки не прерывается.
    """

    collections = (
        "contract_terms",
        "risks",
        "contradictions",
    )

    applicability_statuses = {
        "Применима",
        "Не применима",
        "Требует дополнительной проверки",
        "Недостаточно информации",
    }

    violation_statuses = {
        "Нарушение установлено",
        "Нарушение не установлено",
        "Требует дополнительной проверки",
        "Недостаточно информации",
    }

    def normalize_for_match(value: str) -> str:
        return re.sub(r"\s+", " ", str(value)).strip().casefold()

    items_for_check = []

    for collection_name in collections:
        items = result.get(collection_name, [])

        if not isinstance(items, list):
            continue

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            item["legal_applicability_status"] = "Требует проверки"
            item["legal_applicability_reason"] = (
                "Проверка применимости ещё не выполнена."
            )
            item["legal_applicability_evidence"] = "Не найдено"

            item["legal_violation_status"] = "Требует проверки"
            item["legal_violation_reason"] = (
                "Отдельная проверка нарушения ещё не выполнена."
            )
            item["legal_violation_evidence"] = "Не найдено"

            legal_status = str(
                item.get("legal_basis_status", "")
            ).strip()

            legal_text = str(
                item.get("legal_basis_text", "")
            ).strip()

            legal_basis = str(
                item.get("legal_basis", "")
            ).strip()

            valid_structural_statuses = (
                "Статья найдена",
                "Статья и часть найдены",
                "Структура нормы найдена",
            )

            if (
                legal_status not in valid_structural_statuses
                or not legal_text
                or legal_text.lower() in (
                    "не найдено",
                    "не указано",
                    "не проверено",
                )
                or not legal_basis
                or legal_basis.lower() in (
                    "не найдено",
                    "не указано",
                    "не проверено",
                )
            ):
                item["legal_applicability_reason"] = (
                    "Нельзя проверить применимость: структура "
                    "правовой ссылки или текст нормы не подтверждены."
                )
                item["legal_violation_reason"] = (
                    "Нельзя проверить наличие нарушения: "
                    "правовая ссылка или текст нормы не подтверждены."
                )
                continue

            items_for_check.append({
                "id": f"{collection_name}_{index}",
                "collection": collection_name,
                "category": str(item.get("category", "")),
                "description": str(item.get("description", "")),
                "document_clause": str(item.get("document_clause", "")),
                "document_quote": str(item.get("document_quote", "")),
                "legal_basis": legal_basis,
                "legal_text": legal_text,
            })

    if not items_for_check:
        return result

    prompt = f"""
Ты — специалист по анализу законодательства Российской Федерации
в сфере закупок.

Для каждого переданного условия выполни ДВЕ РАЗДЕЛЬНЫЕ проверки.

ПЕРВАЯ ПРОВЕРКА — ПРИМЕНИМОСТЬ НОРМЫ.

Определи, регулирует ли переданная правовая норма конкретное
условие закупочной документации.

ВТОРАЯ ПРОВЕРКА — НАЛИЧИЕ НАРУШЕНИЯ.

Определи, противоречит ли конкретное условие закупочной документации
требованиям переданной правовой нормы.

ВАЖНО:
Применимость нормы НЕ означает, что закон нарушен.
Само наличие правовой нормы НЕ доказывает нарушение.
Нельзя объявлять нарушение только потому, что условие регулируется
этой нормой.

СТРОГИЕ ПРАВИЛА:

1. Используй только переданные тексты нормы и сведения о закупке.
2. Не придумывай положения законодательства, факты и цитаты.
3. Не добавляй отсутствующие требования закона.
4. Учитывай предмет регулирования, условия, ограничения
   и исключения, если они приведены в тексте нормы.
5. Не считай норму применимой только из-за совпадения слов.
6. Не считай нарушение установленным только из-за применимости нормы.
7. Для статуса «Нарушение установлено» необходимо конкретное
   противоречие между условием документации и требованием нормы.
8. Для каждого установленного нарушения обязательно укажи:
   - document_evidence — дословный фрагмент из document_clause
     или document_quote;
   - legal_evidence — дословный фрагмент из legal_text,
     содержащий соответствующее требование.
9. Оба доказательства должны быть дословными фрагментами
   переданных источников. Не пересказывай их.
10. Если существенных фактов не хватает, не делай предположений.
11. Статус «Нарушение не установлено» не означает,
    что документ полностью соответствует законодательству.
12. Если уверенно определить результат нельзя, используй
    «Требует дополнительной проверки».
13. Если необходимых сведений явно недостаточно, используй
    «Недостаточно информации».
14. Не оценивай и не изменяй коммерческие риски.
15. Верни результат для каждого переданного id.

СТАТУСЫ ПРИМЕНИМОСТИ:
- «Применима»
- «Не применима»
- «Требует дополнительной проверки»
- «Недостаточно информации»

СТАТУСЫ НАРУШЕНИЯ:
- «Нарушение установлено»
- «Нарушение не установлено»
- «Требует дополнительной проверки»
- «Недостаточно информации»

Верни только JSON следующей структуры:
{{
  "results": [
    {{
      "id": "",
      "applicability_status": "",
      "applicability_reason": "",
      "applicability_evidence": "",
      "violation_status": "",
      "violation_reason": "",
      "document_evidence": "",
      "legal_evidence": ""
    }}
  ]
}}

ДАННЫЕ:
{json.dumps(items_for_check, ensure_ascii=False, indent=2)}
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

        parsed = json.loads(response.strip())

        if not isinstance(parsed, dict):
            raise ValueError("Ответ Gemini должен быть JSON-объектом.")

        checked_items = parsed.get("results")

        if not isinstance(checked_items, list):
            raise ValueError("В ответе Gemini отсутствует массив results.")

    except Exception:
        for data in items_for_check:
            index = int(data["id"].rsplit("_", 1)[1])
            target = result[data["collection"]][index]

            target["legal_applicability_reason"] = (
                "Проверка Gemini не выполнена. "
                "Требуется дополнительная проверка."
            )
            target["legal_violation_reason"] = (
                "Проверка нарушения Gemini не выполнена. "
                "Нарушение не подтверждено."
            )

        return result

    expected_ids = {
        item["id"]: item
        for item in items_for_check
    }

    for checked in checked_items:
        if not isinstance(checked, dict):
            continue

        item_id = checked.get("id")

        if item_id not in expected_ids:
            continue

        original = expected_ids[item_id]
        index = int(item_id.rsplit("_", 1)[1])
        target = result[original["collection"]][index]

        applicability_status = str(
            checked.get("applicability_status", "")
        ).strip()

        applicability_reason = str(
            checked.get("applicability_reason", "")
        ).strip()

        applicability_evidence = str(
            checked.get("applicability_evidence", "")
        ).strip()

        if (
            applicability_status in applicability_statuses
            and applicability_reason
        ):
            if applicability_status in (
                "Применима",
                "Не применима",
            ):
                source_text = " ".join((
                    original.get("document_clause", ""),
                    original.get("document_quote", ""),
                    original.get("description", ""),
                    original.get("legal_text", ""),
                ))

                if (
                    not normalize_for_match(applicability_evidence)
                    or normalize_for_match(applicability_evidence)
                    not in normalize_for_match(source_text)
                ):
                    target["legal_applicability_reason"] = (
                        "Ответ Gemini отклонён: доказательство "
                        "применимости отсутствует или не совпадает "
                        "с исходными данными."
                    )
                else:
                    target["legal_applicability_status"] = (
                        applicability_status
                    )
                    target["legal_applicability_reason"] = (
                        applicability_reason
                    )
                    target["legal_applicability_evidence"] = (
                        applicability_evidence
                    )
            else:
                target["legal_applicability_status"] = (
                    applicability_status
                )
                target["legal_applicability_reason"] = (
                    applicability_reason
                )
                target["legal_applicability_evidence"] = (
                    applicability_evidence or "Не найдено"
                )

        violation_status = str(
            checked.get("violation_status", "")
        ).strip()

        violation_reason = str(
            checked.get("violation_reason", "")
        ).strip()

        document_evidence = str(
            checked.get("document_evidence", "")
        ).strip()

        legal_evidence = str(
            checked.get("legal_evidence", "")
        ).strip()

        if (
            violation_status not in violation_statuses
            or not violation_reason
        ):
            target["legal_violation_reason"] = (
                "Ответ Gemini отклонён: отсутствует допустимый "
                "статус нарушения или объяснение."
            )
            continue

        if violation_status == "Нарушение установлено":
            document_source = " ".join((
                original.get("document_clause", ""),
                original.get("document_quote", ""),
            ))

            legal_source = original.get("legal_text", "")

            document_match = (
                bool(normalize_for_match(document_evidence))
                and normalize_for_match(document_evidence)
                in normalize_for_match(document_source)
            )

            legal_match = (
                bool(normalize_for_match(legal_evidence))
                and normalize_for_match(legal_evidence)
                in normalize_for_match(legal_source)
            )

            if not document_match or not legal_match:
                target["legal_violation_status"] = "Требует проверки"
                target["legal_violation_reason"] = (
                    "Ответ Gemini отклонён: не удалось подтвердить "
                    "дословное совпадение доказательств одновременно "
                    "с текстом документа и текстом правовой нормы."
                )
                target["legal_violation_evidence"] = "Не найдено"
                continue

            target["legal_violation_status"] = violation_status
            target["legal_violation_reason"] = violation_reason
            target["legal_violation_evidence"] = (
                f"Документ: {document_evidence} "
                f"| Правовая норма: {legal_evidence}"
            )

        else:
            target["legal_violation_status"] = violation_status
            target["legal_violation_reason"] = violation_reason

            if document_evidence and legal_evidence:
                target["legal_violation_evidence"] = (
                    f"Документ: {document_evidence} "
                    f"| Правовая норма: {legal_evidence}"
                )
            else:
                target["legal_violation_evidence"] = "Не найдено"

    return result

def apply_deterministic_checks(
    result: dict,
    document_text: str,
    procurement_law: str,
) -> dict:
    """Исправляет критически важные поля на основании исходного текста."""

    extracted_type = extract_procurement_type(document_text)

    if extracted_type:
        result["procurement_type"] = extracted_type

    payment_deadline_exists = has_explicit_payment_deadline(document_text)

    collections = (
        "contract_terms",
        "risks",
        "contradictions",
        "commercial_risks",
    )

    for collection_name in collections:
        items = result.get(collection_name, [])

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            category = str(item.get("category", "")).lower()
            description = str(item.get("description", "")).lower()

            is_payment_term = (
                "оплат" in category
                or "расчет" in category
                or "расчёт" in category
                or "оплат" in description
                or "расчет" in description
                or "расчёт" in description
            )

            if is_payment_term and not payment_deadline_exists:
                item["commercial_risk_level"] = "Недостаточно информации"
                item["commercial_risk_reason"] = (
                    "В документе не найден конкретный срок оплаты. "
                    "Невозможно определить продолжительность отсрочки "
                    "и нагрузку на оборотный капитал."
                )

            is_delivery_term = (
                "поставк" in category
                or "срок поставки" in description
                or "срок доставки" in description
            )

            if (
                is_delivery_term
                and collection_name in ("contract_terms", "commercial_risks")
            ):
                item["commercial_risk_level"] = "Недостаточно информации"
                item["commercial_risk_reason"] = (
                    "Срок поставки указан, но для оценки его выполнимости "
                    "недостаточно данных о наличии товара у поставщика, "
                    "объёме партии и логистике. Сам по себе срок поставки "
                    "не подтверждает наличие среднего или высокого "
                    "коммерческого риска."
                )

            if collection_name in (
                "contract_terms",
                "risks",
                "contradictions",
            ):
                legal_status = str(
                    item.get("legal_basis_status", "")
                ).strip()

                legal_text = str(
                    item.get("legal_basis_text", "")
                ).strip()

                legal_basis = str(
                    item.get("legal_basis", "")
                ).strip().lower()

                applicability_status = str(
                    item.get("legal_applicability_status", "")
                ).strip()

                valid_structural_statuses = (
                    "Статья найдена",
                    "Статья и часть найдены",
                    "Структура нормы найдена",
                )

                legal_evidence_confirmed = (
                    legal_status in valid_structural_statuses
                    and bool(legal_text)
                    and legal_text.lower() not in (
                        "не найдено",
                        "не указано",
                        "не проверено",
                    )
                    and legal_basis not in (
                        "",
                        "не найдено",
                        "не указано",
                        "не проверено",
                    )
                )

                applicability_confirmed = (
                    applicability_status == "Применима"
                )

                violation_status = str(
                    item.get("legal_violation_status", "")
                ).strip()

                violation_reason = str(
                    item.get("legal_violation_reason", "")
                ).strip()

                violation_evidence = str(
                    item.get("legal_violation_evidence", "")
                ).strip()

                violation_confirmed = (
                    violation_status == "Нарушение установлено"
                    and bool(violation_reason)
                    and bool(violation_evidence)
                    and violation_evidence.lower() not in (
                        "не найдено",
                        "не указано",
                        "не проверено",
                    )
                )

                legal_assessment_confirmed = (
                    legal_evidence_confirmed
                    and applicability_confirmed
                    and violation_confirmed
                    and LEGAL_VERSION_VERIFIED.get(
                        procurement_law,
                        False,
                    )
                )

                if not legal_assessment_confirmed:
                    item["risk_level"] = "Не определён"

    return result


def find_relevant_legal_articles(
    document_text: str,
    procurement_law: str,
) -> list[dict]:
    version_id = LEGAL_VERSION_IDS.get(procurement_law)

    if not version_id:
        return []

    search_phrases = [
        "обеспечение исполнения контракта",
        "срок поставки",
        "приемка товара",
        "ответственность поставщика",
        "изменение условий контракта",
        "расторжение контракта",
        "односторонний отказ",
    ]

    found_articles = {}
    db = SessionLocal()

    try:
        for phrase in search_phrases:
            if phrase.lower() not in document_text.lower():
                continue

            results = search_legal_provisions(
                db=db,
                version_id=version_id,
                search_text=phrase,
                limit=5,
            )

            for article in results:
                found_articles[article["article_number"]] = article
    finally:
        db.close()

    return list(found_articles.values())


async def analyze_legal_requirements(document_text: str) -> dict:
    if not document_text.strip():
        raise ValueError("Текст документа пуст")

    procurement_law = detect_procurement_law(document_text)

    legal_articles = find_relevant_legal_articles(
        document_text=document_text,
        procurement_law=procurement_law,
    )

    if legal_articles:
        legal_context = "\n\n".join(
            f"СТАТЬЯ {article['article_number']}. "
            f"{article['title']}\n{article['text']}"
            for article in legal_articles
        )
    else:
        legal_context = (
            "Подходящие статьи в локальной базе не найдены. "
            "Не придумывай правовые основания."
        )

    prompt = f"""
Ты — эксперт по анализу закупочной документации в Российской Федерации.
Работаешь с позиции потенциального поставщика.

ПРИМЕНИМЫЙ ЗАКОН:
{procurement_law}

ПРАВОВАЯ БАЗА:
{legal_context}

ВАЖНО О ПРАВОВОЙ БАЗЕ:
- Для разработки используется сохранённая рабочая редакция закона.
- Не утверждай, что она официально проверена на актуальность.
- Используй только переданные статьи.
- Не придумывай номера статей и правовые основания.
- Все найденные основания первоначально имеют статус «Требует проверки».
- После анализа ссылки будут дополнительно проверены программно.

ПРАВИЛА ОПРЕДЕЛЕНИЯ ЗАКУПКИ:

1. Определи предмет закупки по фактическому тексту документа.
2. Если написано «поставка бумажной продукции», укажи
   procurement_type: «Поставка бумажной продукции».
3. Не используй «Не указано», если предмет прямо присутствует
   в исходном тексте.
4. Не путай предмет закупки с видом процедуры.
5. Если вид процедуры не указан, не придумывай его.

ПРАВИЛА ЮРИДИЧЕСКОГО АНАЛИЗА:

1. Разделяй обычные условия контракта и юридические риски.
2. Не называй условие юридическим риском только потому,
   что оно присутствует в контракте.
3. В risks включай только конкретные выявленные риски,
   подтверждаемые текстом и применимыми нормами.
4. Если подтверждённых рисков нет, верни пустой массив risks.
5. Отсутствие информации указывай в missing_information.
6. Для каждого условия приводи точную цитату из документа.
7. Не придумывай номера пунктов, суммы и сроки.
8. Правовое основание указывай только при наличии
   подтверждения в переданном тексте правовой базы.
9. Указывай максимально точную правовую ссылку:
   статью, часть и пункт, если они определяются по тексту нормы.
10. Не ограничивайся номером статьи, если конкретное условие
    регулируется определённой частью или пунктом.
11. Не придумывай номера частей и пунктов.
    Если точную структурную ссылку определить нельзя,
    укажи только подтверждённую часть ссылки.
12. Не делай окончательное юридическое заключение.

ШКАЛА ЮРИДИЧЕСКОГО РИСКА:

- «Низкий» — условие проверено, существенных юридических
  проблем по имеющимся данным не выявлено.
- «Средний» — есть конкретная неопределённость или потенциальная
  проблема, требующая дополнительной проверки.
- «Высокий» — выявлено существенное юридическое нарушение
  или условие с серьёзными последствиями.
- «Критический» — выявлено обстоятельство, которое может
  повлечь крайне серьёзные правовые последствия.
- «Не определён» — имеющихся данных или правовой базы
  недостаточно для оценки.

Не ставь «Низкий» автоматически только потому,
что явного нарушения не обнаружено.
Если редакция закона не проверена и данных недостаточно,
используй «Не определён».

ПРАВИЛА КОММЕРЧЕСКОЙ ОЦЕНКИ:

Для каждого условия в contract_terms и каждого юридического риска
в risks сохраняй отдельную коммерческую оценку для поставщика.

Поле commercial_risk_level должно принимать только одно значение:
- «Низкий»
- «Средний»
- «Высокий»
- «Критический»
- «Недостаточно информации»

Оценивай:
1. Срок поставки и возможность реально выполнить поставку.
2. Необходимость закупать товар за собственные средства.
3. Размер и условия обеспечения исполнения контракта.
4. Сроки оплаты и влияние на оборотный капитал.
5. Риски штрафов, пеней и удержаний.
6. Возможность изменения объёма и условий поставки.
7. Логистические и складские затраты.
8. Риск снижения или потери прибыли.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:

1. Не придумывай закупочные цены, себестоимость и прибыль.
2. Не рассчитывай прибыль без цены контракта и затрат.
3. Не объявляй условие незаконным только потому,
   что оно коммерчески невыгодно.
4. Короткий срок поставки сам по себе не означает высокий риск.
5. Учитывай объём, наличие товара, расстояние и логистику.
   Если данных нет, прямо укажи это в commercial_risk_reason.
6. Отсутствие размера обеспечения означает недостаток информации,
   а не автоматически высокий риск.
7. Если указан факт оплаты после приёмки, но не указан срок оплаты,
   используй «Недостаточно информации».
8. Если данных недостаточно, используй «Недостаточно информации».
9. Не присваивай уровни «Средний», «Высокий» или «Критический»
   на основании предположений о возможных последствиях.
10. Если для оценки конкретного риска отсутствуют существенные
    сведения, используй «Недостаточно информации».
11. Если один и тот же коммерческий риск отражён одновременно
    в contract_terms и commercial_risks, оценки должны быть
    согласованы между собой.
12. Не повышай уровень коммерческого риска только из-за того,
    что потенциально возможны финансовые потери.
13. Объясняй коммерческую оценку в commercial_risk_reason.
14. Юридический и коммерческий риски оценивай независимо.

ОТДЕЛЬНЫЙ РАЗДЕЛ COMMERCIAL_RISKS:

В commercial_risks включай самостоятельные существенные
коммерческие угрозы для потенциального поставщика.

Примеры:
- риск кассового разрыва из-за условий оплаты;
- риск невозможности выполнить поставку в установленный срок;
- риск убытка из-за логистических или складских расходов;
- риск недостаточной рентабельности;
- риск необходимости значительного предварительного финансирования;
- риск финансовых потерь из-за штрафов и пеней.

Правила заполнения:
1. Не копируй в commercial_risks каждое обычное условие контракта.
2. Выноси туда именно коммерческое последствие или угрозу
   для поставщика, а не просто описание условия.
3. Не дублируй один и тот же риск несколько раз.
4. Не придумывай факты, суммы, цены и расчёты.
5. Если для оценки не хватает данных, укажи
   «Недостаточно информации» и объясни, каких данных не хватает.
6. Не включай коммерческие риски в risks:
   risks предназначен только для юридических рисков.
7. Не указывай правовые основания для чисто коммерческих рисков.

КЛАССИФИКАЦИЯ:

- contract_terms: обычные условия закупки и контракта.
- risks: подтверждённые юридические риски.
- commercial_risks: самостоятельные коммерческие угрозы для поставщика.
- contradictions: противоречия в документации.
- missing_information: важные отсутствующие сведения.
- questions_to_customer: конкретные вопросы для уточнения.

Проверь, чтобы каждый объект в contract_terms, risks
и contradictions содержал все предусмотренные поля.
Каждый объект commercial_risks должен содержать:
category, description, commercial_risk_level,
commercial_risk_reason, document_clause, document_quote,
recommendation.

Не добавляй сведения, которых нет в исходном документе.

Верни только корректный JSON без Markdown.

СТРУКТУРА:
{{
  "procurement_law": "",
  "procurement_type": "",
  "contract_terms": [],
  "risks": [],
  "commercial_risks": [],
  "contradictions": [],
  "missing_information": [],
  "questions_to_customer": [],
  "overall_conclusion": ""
}}

В каждом объекте contract_terms, risks и contradictions используй поля:

{{
  "category": "",
  "description": "",
  "risk_level": "",
  "commercial_risk_level": "",
  "commercial_risk_reason": "",
  "document_clause": "",
  "document_quote": "",
  "legal_basis": "",
  "legal_basis_status": "",
  "recommendation": ""
}}

В каждом объекте commercial_risks используй поля:

{{
  "category": "",
  "description": "",
  "commercial_risk_level": "",
  "commercial_risk_reason": "",
  "document_clause": "",
  "document_quote": "",
  "recommendation": ""
}}

ИСХОДНЫЙ ТЕКСТ ДОКУМЕНТА:
{document_text}
"""

    result = await generate_text(prompt, json_mode=True)
    result = result.strip()

    if result.startswith("```json"):
        result = result[7:]
    elif result.startswith("```"):
        result = result[3:]

    if result.endswith("```"):
        result = result[:-3]

    try:
        parsed_result = json.loads(result.strip())
    except json.JSONDecodeError as error:
        lines = result.splitlines()
        start = max(0, error.lineno - 4)
        end = min(len(lines), error.lineno + 3)
        context = "\\n".join(
            f"{index + 1}: {lines[index]}"
            for index in range(start, end)
        )

        raise RuntimeError(
            f"Gemini вернул некорректный JSON: {error}\\n"
            f"Фрагмент ответа около ошибки:\\n{context}"
        ) from error

    try:
        validated_result = LegalAnalysis.model_validate(parsed_result)
    except ValidationError as error:
        raise RuntimeError(
            f"Gemini вернул данные неправильной структуры: {error}"
        ) from error

    result_data = validated_result.model_dump()
    result_data["procurement_law"] = procurement_law

    result_data = validate_result_legal_references(
        result=result_data,
        procurement_law=procurement_law,
    )

    result_data = await check_legal_applicability(
        result=result_data,
    )

    result_data = apply_deterministic_checks(
        result=result_data,
        document_text=document_text,
        procurement_law=procurement_law,
    )

    return result_data
