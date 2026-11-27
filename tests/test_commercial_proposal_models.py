from sqlalchemy import inspect

from app.database import engine
from app.commercial.models import CommercialProposalDB, CommercialProposalItemDB, CommercialMatchEvidenceVerificationDB


def test_commercial_proposal_tables_are_migrated():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert CommercialProposalDB.__tablename__ in tables
    assert CommercialProposalItemDB.__tablename__ in tables

    proposal_columns = {
        column["name"]
        for column in inspector.get_columns("commercial_proposals")
    }
    assert {
        "commercial_analysis_id",
        "tender_analysis_id",
        "version",
        "status",
        "total_amount",
        "known_total_amount",
        "issues",
    } <= proposal_columns

    item_columns = {
        column["name"]
        for column in inspector.get_columns("commercial_proposal_items")
    }
    assert {
        "proposal_id",
        "requirement_text_snapshot",
        "product_name_snapshot",
        "supplier_name_snapshot",
        "offer_price_snapshot",
        "offer_currency_snapshot",
        "quantity",
        "unit_price",
        "line_total",
        "evidence_references_snapshot",
        "evidence_verified_at_snapshot",
        "evidence_verified_by_snapshot",
        "evidence_basis_snapshot",
        "evidence_reference_snapshot",
        "evidence_notes_snapshot",
        "source_references",
    } <= item_columns

    proposal_fks = inspector.get_foreign_keys("commercial_proposals")
    assert any(
        fk["referred_table"] == "commercial_analyses"
        and fk["options"].get("ondelete") == "CASCADE"
        for fk in proposal_fks
    )

    item_fks = inspector.get_foreign_keys("commercial_proposal_items")
    assert any(
        fk["constrained_columns"] == ["proposal_id"]
        and fk["options"].get("ondelete") == "CASCADE"
        for fk in item_fks
    )
    assert any(
        fk["constrained_columns"] == ["offer_id"]
        and fk["options"].get("ondelete") == "SET NULL"
        for fk in item_fks
    )


def test_manual_evidence_verification_table_and_proposal_snapshots_are_migrated():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert CommercialMatchEvidenceVerificationDB.__tablename__ in tables
    columns = {
        column["name"]
        for column in inspector.get_columns("commercial_match_evidence_verifications")
    }
    assert {
        "commercial_match_id", "verification_status", "verified_at",
        "verified_by", "basis", "evidence_reference", "notes",
    } <= columns
