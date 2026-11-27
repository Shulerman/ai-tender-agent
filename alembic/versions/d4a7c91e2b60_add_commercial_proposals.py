"""Add versioned commercial proposals and immutable item snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "d4a7c91e2b60"
down_revision = "6f9d2c8a4b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commercial_analysis_id", sa.Integer(), nullable=False),
        sa.Column("tender_analysis_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("known_total_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_commercial_proposal_version_positive"),
        sa.CheckConstraint(
            "status IN ('Черновик', 'Неполное', 'Готово')",
            name="ck_commercial_proposal_status",
        ),
        sa.ForeignKeyConstraint(
            ["commercial_analysis_id"], ["commercial_analyses.id"],
            name="fk_commercial_proposals_analysis", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_analysis_id"], ["tender_analyses.id"],
            name="fk_commercial_proposals_tender_analysis", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "commercial_analysis_id", "version",
            name="uq_commercial_proposal_analysis_version",
        ),
    )
    op.create_index(
        "ix_commercial_proposals_commercial_analysis_id",
        "commercial_proposals", ["commercial_analysis_id"],
    )
    op.create_index(
        "ix_commercial_proposals_tender_analysis_id",
        "commercial_proposals", ["tender_analysis_id"],
    )

    op.create_table(
        "commercial_proposal_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("tender_requirement_id", sa.Integer(), nullable=True),
        sa.Column("commercial_match_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("offer_id", sa.Integer(), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("position_number", sa.Integer(), nullable=True),
        sa.Column("requirement_text_snapshot", sa.Text(), nullable=False),
        sa.Column("product_name_snapshot", sa.String(), nullable=True),
        sa.Column("product_article_snapshot", sa.String(), nullable=True),
        sa.Column("manufacturer_name_snapshot", sa.String(), nullable=True),
        sa.Column("product_description_snapshot", sa.Text(), nullable=True),
        sa.Column("technical_characteristics_snapshot", sa.Text(), nullable=True),
        sa.Column("technical_attributes_snapshot", sa.JSON(), nullable=True),
        sa.Column("product_unit_snapshot", sa.String(), nullable=True),
        sa.Column("supplier_name_snapshot", sa.String(), nullable=True),
        sa.Column("offer_price_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("offer_currency_snapshot", sa.String(length=3), nullable=True),
        sa.Column("offer_unit_snapshot", sa.String(), nullable=True),
        sa.Column("available_quantity_snapshot", sa.Numeric(14, 3), nullable=True),
        sa.Column("availability_status_snapshot", sa.String(), nullable=True),
        sa.Column("delivery_time_days_snapshot", sa.Integer(), nullable=True),
        sa.Column("payment_terms_snapshot", sa.Text(), nullable=True),
        sa.Column("delivery_cost_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("offer_received_at_snapshot", sa.DateTime(), nullable=True),
        sa.Column("offer_valid_until_snapshot", sa.DateTime(), nullable=True),
        sa.Column("offer_verification_status_snapshot", sa.String(), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("line_total", sa.Numeric(16, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_verification_status", sa.String(), nullable=False),
        sa.Column("match_status_snapshot", sa.String(), nullable=True),
        sa.Column("match_score_snapshot", sa.Numeric(5, 2), nullable=True),
        sa.Column("confirmed_characteristics_snapshot", sa.Text(), nullable=True),
        sa.Column("missing_characteristics_snapshot", sa.Text(), nullable=True),
        sa.Column("discrepancies_snapshot", sa.Text(), nullable=True),
        sa.Column("evidence_status_snapshot", sa.String(), nullable=True),
        sa.Column("evidence_references_snapshot", sa.Text(), nullable=True),
        sa.Column("source_references", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_commercial_proposal_item_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="ck_commercial_proposal_item_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "line_total IS NULL OR line_total >= 0",
            name="ck_commercial_proposal_item_line_total_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["commercial_proposals.id"],
            name="fk_commercial_proposal_items_proposal", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_requirement_id"], ["tender_requirements.id"],
            name="fk_commercial_proposal_items_requirement", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["commercial_match_id"], ["commercial_matches.id"],
            name="fk_commercial_proposal_items_match", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_commercial_proposal_items_product", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["offer_id"], ["supplier_offers.id"],
            name="fk_commercial_proposal_items_offer", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"],
            name="fk_commercial_proposal_items_supplier", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in (
        "proposal_id", "tender_requirement_id", "commercial_match_id",
        "product_id", "offer_id", "supplier_id",
    ):
        op.create_index(
            f"ix_commercial_proposal_items_{column}",
            "commercial_proposal_items", [column],
        )


def downgrade() -> None:
    op.drop_table("commercial_proposal_items")
    op.drop_index(
        "ix_commercial_proposals_tender_analysis_id",
        table_name="commercial_proposals",
    )
    op.drop_index(
        "ix_commercial_proposals_commercial_analysis_id",
        table_name="commercial_proposals",
    )
    op.drop_table("commercial_proposals")
