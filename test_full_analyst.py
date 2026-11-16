from unittest.mock import AsyncMock, patch

import pytest

from app.ai.full_analyst import analyze_full_tender


@pytest.mark.asyncio
async def test_full_analyst_success():
    document_text = "Test procurement: paper supply."

    technical_result = {
        "products": [{"name": "Paper", "quantity": 100}]
    }

    legal_result = {
        "procurement_law": "44-FZ",
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


@pytest.mark.asyncio
async def test_full_analyst_rejects_empty_document():
    with patch(
        "app.ai.full_analyst.analyze_technical_requirements",
        new_callable=AsyncMock,
    ) as technical_mock, patch(
        "app.ai.full_analyst.analyze_legal_requirements",
        new_callable=AsyncMock,
    ) as legal_mock:

        with pytest.raises(ValueError):
            await analyze_full_tender("   ")

        technical_mock.assert_not_awaited()
        legal_mock.assert_not_awaited()
