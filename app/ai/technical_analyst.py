
import json

from pydantic import ValidationError

from app.ai.gemini import generate_text
from app.ai.technical_models import TechnicalAnalysis


async def analyze_technical_requirements(document_text: str) -> dict:
    """
    Анализирует техническое задание закупки с помощью Gemini
    и проверяет структуру результата через Pydantic.
    """

    if not document_text.strip():
        raise ValueError("Текст документа пуст")

    prompt = f"""
Ты — технический аналитик государственных и коммерческих закупок.

Проанализируй текст технического задания.

ТВОИ ЗАДАЧИ:

1. Выдели все товары и материалы.
2. Для каждого товара укажи:
   - name: наименование;
   - quantity: количество;
   - unit: единицу измерения;
   - technical_characteristics: технические характеристики;
   - packaging_requirements: требования к упаковке;
   - quality_and_standards: требования к качеству и стандартам;
   - quotes: точные цитаты из документа.
3. Выдели сроки и условия поставки.
   - Обязательно извлекай сроки из любого места документа.
   - Не оставляй delivery_time как «Не указано», если срок присутствует в тексте.
   - Например: «3 рабочих дня после заявки; срочная поставка — 1 рабочий день».
   4. Укажи адреса доставки, если они есть.
5. Выдели требования к образцам, сертификатам и декларациям.
6. Найди противоречия, неясные формулировки и недостающие данные.
7. Составь список вопросов заказчику.

ВАЖНЫЕ ПРАВИЛА:

- Не придумывай отсутствующие сведения.
- Если информации нет, укажи «Не указано».
- Сохраняй исходные единицы измерения и количества.
- Для важных требований приводи точные цитаты.
- Не подменяй требования заказчика предположениями.

Верни только JSON без Markdown-разметки.

Структура JSON:

{{
  "products": [],
  "delivery_requirements": [],
  "document_requirements": [],
  "risks_and_uncertainties": [],
  "questions_to_customer": []
}}

ТЕКСТ ТЕХНИЧЕСКОГО ЗАДАНИЯ:

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

    result = result.strip()

    try:
        parsed_result = json.loads(result)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Gemini вернул некорректный JSON: {error}"
        ) from error

    try:
        validated_result = TechnicalAnalysis.model_validate(parsed_result)
    except ValidationError as error:
        raise RuntimeError(
            f"Gemini вернул данные неправильной структуры: {error}"
        ) from error

    return validated_result.model_dump()
