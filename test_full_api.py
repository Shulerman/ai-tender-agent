from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_full_analysis_endpoint():
    document_text = "Тестовая закупка: поставка бумажной продукции."
    fake_result = {
        "status": "success",
        "document_text_length": len(document_text),
        "technical_analysis": {"products": [{"name": "Бумага"}]},
        "legal_analysis": {"procurement_law": "44-ФЗ"},
    }

    with patch(
        "app.main.analyze_full_tender",
        new_callable=AsyncMock,
    ) as analyzer:
        analyzer.return_value = fake_result

        response = client.post(
            "/analysis/full",
            json={"document_text": document_text},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["message"] == "Full tender analysis completed"
        assert body["analysis"] == fake_result
        analyzer.assert_awaited_once_with(document_text)

    print("1. Полный анализ возвращает HTTP 200.")
    print("2. Результаты технического и юридического анализа сохранены.")

    with patch(
        "app.main.analyze_full_tender",
        new_callable=AsyncMock,
    ) as analyzer:
        response = client.post(
            "/analysis/full",
            json={"document_text": "   "},
        )

        assert response.status_code == 400, response.text
        analyzer.assert_not_awaited()

    print("3. Пустой документ отклоняется с HTTP 400.")
    print("4. Анализатор не вызывается для пустого документа.")

    with patch(
        "app.main.analyze_full_tender",
        new_callable=AsyncMock,
    ) as analyzer:
        response = client.post("/analysis/full", json={})

        assert response.status_code == 400, response.text
        analyzer.assert_not_awaited()

    print("5. Отсутствующий текст отклоняется с HTTP 400.")
    print()
    print("ТЕСТ API-МАРШРУТА /analysis/full ПРОЙДЕН")


if __name__ == "__main__":
    test_full_analysis_endpoint()
