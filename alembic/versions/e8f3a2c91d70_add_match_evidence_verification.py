"""Add manual commercial match evidence verification history."""

from alembic import op
import sqlalchemy as sa

revision = "e8f3a2c91d70"
down_revision = "d4a7c91e2b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_match_evidence_verifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commercial_match_id", sa.Integer(), nullable=False),
        sa.Column("verification_status", sa.String(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.Column("verified_by", sa.String(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "verification_status IN ('Подтверждено', 'Отклонено')",
            name="ck_commercial_match_evidence_verification_status",
        ),
        sa.ForeignKeyConstraint(
            ["commercial_match_id"], ["commercial_matches.id"],
            name="fk_commercial_match_evidence_verifications_match",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_commercial_match_evidence_verifications_id",
        "commercial_match_evidence_verifications", ["id"],
    )
    op.create_index(
        "ix_commercial_match_evidence_verifications_commercial_match_id",
        "commercial_match_evidence_verifications", ["commercial_match_id"],
    )
    for name, kind in (
        ("evidence_verified_at_snapshot", sa.DateTime()),
        ("evidence_verified_by_snapshot", sa.String()),
        ("evidence_basis_snapshot", sa.Text()),
        ("evidence_reference_snapshot", sa.Text()),
        ("evidence_notes_snapshot", sa.Text()),
    ):
        op.add_column("commercial_proposal_items", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    for name in (
        "evidence_notes_snapshot", "evidence_reference_snapshot",
        "evidence_basis_snapshot", "evidence_verified_by_snapshot",
        "evidence_verified_at_snapshot",
    ):
        op.drop_column("commercial_proposal_items", name)
    op.drop_index(
        "ix_commercial_match_evidence_verifications_commercial_match_id",
        table_name="commercial_match_evidence_verifications",
    )
    op.drop_index(
        "ix_commercial_match_evidence_verifications_id",
        table_name="commercial_match_evidence_verifications",
    )
    op.drop_table("commercial_match_evidence_verifications")
