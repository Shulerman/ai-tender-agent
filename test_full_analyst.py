import asyncio
from unittest.mock import AsyncMock, patch

from app.ai.full_analyst import analyze_full_tender


async def main():
    document_text = "Тестовая закупка: поставка бумажной продукции."

    technical_result = {
        "products": [{"name": "Бумага", "quantity": 100}]
    }
    legal_result = {
        "procurement_law": "44-ФЗ",
        "risks": [],
    }

    with patch(
        "app.ai.full_analyst.analyze_technical_requirements",
        new_callable=AsyncMock,
    ) as technical_mock, patch(
        "app.ai.full_analyst.analyze_legal_requirements",
        new_callable=AsyncMock,
    ) as legal_mock:

        technical_mock.return_value = technical_result
        legal_mock.return_value = legal_result

        result = await analyze_full_tender(document_text)

        technical_mock.assert_awaited_once_with(document_text)
        legal_mock.assert_awaited_once_with(document_text)

        assert result["status"] == "success"
        assert result["document_text_length"] == len(document_text)
        assert result["technical_analysis"] == technical_result
        assert result["legal_analysis"] == legal_result

    print("ОСНОВНОЙ ТЕСТ ПРОЙДЕН")
    print("1. Оба анализатора получили один исходный текст.")
    print("2. Оба анализатора вызваны ровно один раз.")
    print("3. Технический результат сохранён.")
    print("4. Юридический результат сохранён.")

    with patch(
        "app.ai.full_analyst.analyze_technical_requirements",
        new_callable=AsyncMock,
    ) as technical_mock, patch(
        "app.ai.full_analyst.analyze_legal_requirements",
        new_callable=AsyncMock,
    ) as legal_mock:

        try:
            await analyze_full_tender("   ")
        except ValueError as error:
            assert str(error) == "Текст документа пуст"
        else:
            raise AssertionError("Пустой документ не был отклонён")

        technical_mock.assert_not_awaited()
        legal_mock.assert_not_awaited()

    print("5. Пустой документ корректно отклоняется.")
    print()
    print("ТЕСТ ОБЪЕДИНЁННОГО АНАЛИЗАТОРА ПРОЙДЕН")


asyncio.run(main())
