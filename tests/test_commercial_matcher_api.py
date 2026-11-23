from datetime import datetime, timedelta
import uuid

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import SessionLocal, TenderDB
from app.documents.models import (
    TenderDocumentDB,
    TenderAnalysisDB,
    TenderRequirementDB,
)
from app.commercial.models import (
    CommercialAnalysisDB,
    CommercialMatchRunDB,
    CommercialMatchDB,
    ProductDB,
    SupplierDB,
    SupplierOfferDB,
)
from app.commercial.service import create_commercial_analysis


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    main_module.app.dependency_overrides[main_module.get_db] = override_get_db
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_db, None)


def create_scenario(db, analysis_type="technical_requirements",
                    status="Завершён"):
    suffix = uuid.uuid4().hex
    tender = TenderDB(
        tender_id=f"MATCHER-API-{suffix}",
        title="Тестовый тендер API matcher",
    )
    db.add(tender)
    db.commit()
    db.refresh(tender)

    commercial_analysis = create_commercial_analysis(
        db,
        {"tender_id": tender.tender_id},
    )

    document = TenderDocumentDB(
        document_uuid=str(uuid.uuid4()),
        tender_id=tender.id,
        original_name="matcher_api_test.html",
        file_path="matcher_api_test.html",
        file_hash=None,
        detected_extension=".html",
        size_bytes=100,
    )
    db.add(document)
    db.flush()

    tender_analysis = TenderAnalysisDB(
        document_id=document.id,
        analysis_type=analysis_type,
        status=status,
        result_json={},
    )
    db.add(tender_analysis)
    db.flush()

    requirement = TenderRequirementDB(
        document_id=document.id,
        analysis_id=tender_analysis.id,
        requirement_type="product",
        requirement_text="Тестовое требование: диаметр 10 мм, сталь",
        attributes={
            "name": "Тестовый товар",
            "attributes": [
                {
                    "name": "diameter",
                    "value": 10,
                    "unit": "mm",
                    "operator": "=",
                    "is_required": True,
                    "evidence": [],
                },
                {
                    "name": "material",
                    "value": "steel",
                    "unit": None,
                    "operator": "=",
                    "is_required": True,
                    "evidence": [],
                },
            ],
        },
        evidence_quote="Тестовое требование",
        extraction_status="Проверено",
    )
    db.add(requirement)
    db.commit()
    db.refresh(tender_analysis)
    db.refresh(requirement)

    return tender, commercial_analysis, tender_analysis, requirement


def test_run_matcher_api_returns_run_and_statistics(client, db):
    _, analysis, tender_analysis, _ = create_scenario(db)

    response = client.post(
        f"/commercial/analyses/{analysis.id}/matches/run",
        json={"tender_analysis_id": tender_analysis.id},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["id"] is not None
    assert result["commercial_analysis_id"] == analysis.id
    assert result["tender_analysis_id"] == tender_analysis.id
    assert result["status"] == "Завершён"
    assert isinstance(result["statistics"], dict)
    assert result["statistics"]["requirements_total"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tender_analysis_id": 1, "unexpected": True},
        {"tender_analysis_id": 0},
        {"tender_analysis_id": -1},
        {"tender_analysis_id": "1"},
        {"tender_analysis_id": True},
        {"tender_analysis_id": None},
    ],
)
def test_run_matcher_api_rejects_invalid_payload(client, db, payload):
    _, analysis, _, _ = create_scenario(db)

    response = client.post(
        f"/commercial/analyses/{analysis.id}/matches/run",
        json=payload,
    )

    assert response.status_code == 422


def test_run_matcher_api_returns_404_for_missing_analyses(client, db):
    _, analysis, _, _ = create_scenario(db)

    missing_commercial = client.post(
        "/commercial/analyses/999999/matches/run",
        json={"tender_analysis_id": 1},
    )
    assert missing_commercial.status_code == 404

    missing_tender_analysis = client.post(
        f"/commercial/analyses/{analysis.id}/matches/run",
        json={"tender_analysis_id": 999999},
    )
    assert missing_tender_analysis.status_code == 404


@pytest.mark.parametrize(
    ("analysis_type", "status", "expected_detail"),
    [
        (
            "other_analysis",
            "Завершён",
            "Выбранный анализ не является техническим анализом",
        ),
        (
            "technical_requirements",
            "Выполняется",
            "Технический анализ ещё не завершён",
        ),
    ],
)
def test_run_matcher_api_rejects_ineligible_tender_analysis(
    client, db, analysis_type, status, expected_detail
):
    _, analysis, tender_analysis, _ = create_scenario(
        db,
        analysis_type=analysis_type,
        status=status,
    )

    response = client.post(
        f"/commercial/analyses/{analysis.id}/matches/run",
        json={"tender_analysis_id": tender_analysis.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


def test_matcher_api_returns_history_and_separates_match_types(client, db):
    _, analysis, tender_analysis, _ = create_scenario(db)

    full_product = ProductDB(
        name=f"API полное соответствие {uuid.uuid4().hex}",
        technical_attributes={
            "diameter": {"value": 10, "unit": "mm"},
            "material": "steel",
        },
    )
    analogue_product = ProductDB(
        name=f"API потенциальный аналог {uuid.uuid4().hex}",
        technical_attributes={
            "diameter": {"value": 10, "unit": "mm"},
        },
    )
    db.add_all([full_product, analogue_product])
    db.commit()

    run_ids = []
    for _ in range(2):
        response = client.post(
            f"/commercial/analyses/{analysis.id}/matches/run",
            json={"tender_analysis_id": tender_analysis.id},
        )
        assert response.status_code == 200
        run_ids.append(response.json()["id"])

    history_response = client.get(
        f"/commercial/analyses/{analysis.id}/match-runs"
    )
    assert history_response.status_code == 200

    history = history_response.json()
    assert len(history) == 2
    assert [item["id"] for item in history] == list(reversed(run_ids))

    matches_response = client.get(
        f"/commercial/analyses/{analysis.id}/matches",
        params={"run_id": run_ids[0]},
    )
    assert matches_response.status_code == 200

    result = matches_response.json()
    assert result["analysis_id"] == analysis.id
    assert result["run_id"] == run_ids[0]

    full_ids = {
        item["product"]["id"]
        for item in result["full_matches"]
        if item["product"] is not None
    }
    analogue_ids = {
        item["product"]["id"]
        for item in result["potential_analogues"]
        if item["product"] is not None
    }

    assert full_product.id in full_ids
    assert analogue_product.id in analogue_ids
    assert full_product.id not in analogue_ids
    assert analogue_product.id not in full_ids


def test_matcher_api_returns_empty_results_without_runs(client, db):
    _, analysis, _, _ = create_scenario(db)

    history_response = client.get(
        f"/commercial/analyses/{analysis.id}/match-runs"
    )
    assert history_response.status_code == 200
    assert history_response.json() == []

    matches_response = client.get(
        f"/commercial/analyses/{analysis.id}/matches"
    )
    assert matches_response.status_code == 200
    assert matches_response.json() == {
        "analysis_id": analysis.id,
        "run_id": None,
        "full_matches": [],
        "potential_analogues": [],
    }


def test_matcher_api_rejects_unknown_or_foreign_run_id(client, db):
    _, analysis, tender_analysis, _ = create_scenario(db)
    _, other_analysis, _, _ = create_scenario(db)

    run = CommercialMatchRunDB(
        commercial_analysis_id=other_analysis.id,
        tender_analysis_id=tender_analysis.id,
        status="Завершён",
        algorithm_version="test",
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    unknown = client.get(
        f"/commercial/analyses/{analysis.id}/matches",
        params={"run_id": 999999},
    )
    assert unknown.status_code == 404

    foreign = client.get(
        f"/commercial/analyses/{analysis.id}/matches",
        params={"run_id": run.id},
    )
    assert foreign.status_code == 404


def test_matcher_api_returns_404_for_unknown_analysis(client):
    assert client.get(
        "/commercial/analyses/999999/match-runs"
    ).status_code == 404

    assert client.get(
        "/commercial/analyses/999999/matches"
    ).status_code == 404

def test_compare_offers_api_returns_ranked_offers(client, db):
    _, analysis, _, _ = create_scenario(db)

    product = ProductDB(
        name=f"Тестовый товар сравнения {uuid.uuid4().hex}",
        unit="шт.",
    )
    supplier = SupplierDB(name=f"Тестовый поставщик {uuid.uuid4().hex}")
    db.add_all([product, supplier])
    db.flush()

    match = CommercialMatchDB(
        analysis_id=analysis.id,
        product_id=product.id,
        tender_requirement="10 штук",
        match_status="Полное соответствие",
        estimated_quantity=10,
    )
    db.add(match)
    db.flush()

    offer = SupplierOfferDB(
        supplier_id=supplier.id,
        product_id=product.id,
        price=150,
        unit="шт.",
        available_quantity=100,
        delivery_cost=0,
        received_at=datetime.now(),
        valid_until=datetime.now() + timedelta(days=5),
        source_type="manual",
        verification_status="Подтверждено",
    )
    db.add(offer)
    db.commit()
    db.refresh(match)

    response = client.get(
        f"/commercial/analyses/{analysis.id}/matches/{match.id}/offers/compare"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["analysis_id"] == analysis.id
    assert result["match_id"] == match.id
    assert result["product_id"] == product.id
    assert float(result["estimated_quantity"]) == 10
    assert len(result["ranked_offers"]) == 1
    assert result["ranked_offers"][0]["supplier_name"] == supplier.name
    assert float(result["ranked_offers"][0]["landed_total"]) == 1500
    assert result["unranked_offers"] == []
    assert result["expired_offers"] == []


def test_compare_offers_api_rejects_missing_estimated_quantity(client, db):
    _, analysis, _, _ = create_scenario(db)

    product = ProductDB(
        name=f"Товар без количества {uuid.uuid4().hex}",
        unit="шт.",
    )
    db.add(product)
    db.flush()

    match = CommercialMatchDB(
        analysis_id=analysis.id,
        product_id=product.id,
        tender_requirement="Количество не указано",
        match_status="Полное соответствие",
        estimated_quantity=None,
    )
    db.add(match)
    db.commit()

    response = client.get(
        f"/commercial/analyses/{analysis.id}/matches/{match.id}/offers/compare"
    )

    assert response.status_code == 422
    assert "количество не определено" in response.json()["detail"]


def test_compare_offers_api_rejects_match_from_another_analysis(client, db):
    _, analysis, _, _ = create_scenario(db)
    _, other_analysis, _, _ = create_scenario(db)

    product = ProductDB(
        name=f"Чужой товар {uuid.uuid4().hex}",
        unit="шт.",
    )
    db.add(product)
    db.flush()

    match = CommercialMatchDB(
        analysis_id=other_analysis.id,
        product_id=product.id,
        tender_requirement="10 штук",
        match_status="Полное соответствие",
        estimated_quantity=10,
    )
    db.add(match)
    db.commit()

    response = client.get(
        f"/commercial/analyses/{analysis.id}/matches/{match.id}/offers/compare"
    )

    assert response.status_code == 404



def _create_match_with_offer(db, verification_status="Не проверено", expired=False):
    _, analysis, _, _ = create_scenario(db)

    product = ProductDB(
        name=f"Товар выбора предложения {uuid.uuid4().hex}",
        unit="шт.",
    )
    supplier = SupplierDB(
        name=f"Поставщик выбора предложения {uuid.uuid4().hex}"
    )
    db.add_all([product, supplier])
    db.flush()

    match = CommercialMatchDB(
        analysis_id=analysis.id,
        product_id=product.id,
        tender_requirement="10 штук",
        match_status="Полное соответствие",
        estimated_quantity=10,
        notes="Существующая заметка",
    )
    db.add(match)
    db.flush()

    offer = SupplierOfferDB(
        supplier_id=supplier.id,
        product_id=product.id,
        price=150,
        currency="RUB",
        unit="шт.",
        available_quantity=100,
        delivery_cost=100,
        received_at=datetime.now(),
        valid_until=(
            datetime.now() - timedelta(days=1)
            if expired
            else datetime.now() + timedelta(days=5)
        ),
        source_type="manual",
        verification_status=verification_status,
    )
    db.add(offer)
    db.commit()
    db.refresh(match)
    db.refresh(offer)

    return analysis, match, offer


def test_select_commercial_match_offer_saves_calculated_prices(client, db):
    analysis, match, offer = _create_match_with_offer(db)

    response = client.put(
        f"/commercial/analyses/{analysis.id}/matches/{match.id}/offer",
        json={"offer_id": offer.id},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["offer_id"] == offer.id
    assert result["verification_status"] == "Не проверено"
    assert float(result["estimated_unit_price"]) == 150
    assert float(result["estimated_total_price"]) == 1600
    assert result["currency"] == "RUB"

    db.refresh(match)
    assert match.offer_id == offer.id
    assert float(match.estimated_unit_price) == 150
    assert float(match.estimated_total_price) == 1600
    assert match.notes == "Существующая заметка"


def test_select_commercial_match_offer_rejects_expired_offer(client, db):
    analysis, match, offer = _create_match_with_offer(db, expired=True)

    response = client.put(
        f"/commercial/analyses/{analysis.id}/matches/{match.id}/offer",
        json={"offer_id": offer.id},
    )

    assert response.status_code == 422
    db.refresh(match)
    assert match.offer_id is None


def test_select_commercial_match_offer_rejects_declined_offer(client, db):
    analysis, match, offer = _create_match_with_offer(
        db,
        verification_status="Отклонено",
    )

    response = client.put(
        f"/commercial/analyses/{analysis.id}/matches/{match.id}/offer",
        json={"offer_id": offer.id},
    )

    assert response.status_code == 422
    db.refresh(match)
    assert match.offer_id is None
