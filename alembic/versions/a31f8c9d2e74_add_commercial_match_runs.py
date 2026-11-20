"""Add commercial match runs and structured product attributes.

Revision ID: a31f8c9d2e74
Revises: 91617b620d0b
Create Date: 2026-11-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a31f8c9d2e74"
down_revision: Union[str, Sequence[str], None] = "91617b620d0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("technical_attributes", sa.JSON(), nullable=True),
    )

    op.create_table(
        "commercial_match_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commercial_analysis_id", sa.Integer(), nullable=False),
        sa.Column("tender_analysis_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("algorithm_version", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("statistics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["commercial_analysis_id"],
            ["commercial_analyses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_analysis_id"],
            ["tender_analyses.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_commercial_match_runs_commercial_analysis_id",
        "commercial_match_runs",
        ["commercial_analysis_id"],
    )
    op.create_index(
        "ix_commercial_match_runs_tender_analysis_id",
        "commercial_match_runs",
        ["tender_analysis_id"],
    )

    op.add_column(
        "commercial_matches",
        sa.Column("tender_requirement_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "commercial_matches",
        sa.Column("match_run_id", sa.Integer(), nullable=True),
    )

    with op.batch_alter_table("commercial_matches") as batch_op:
        batch_op.create_foreign_key(
            "fk_commercial_matches_tender_requirement",
            "tender_requirements",
            ["tender_requirement_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_commercial_matches_match_run",
            "commercial_match_runs",
            ["match_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        "ix_commercial_matches_tender_requirement_id",
        "commercial_matches",
        ["tender_requirement_id"],
    )
    op.create_index(
        "ix_commercial_matches_match_run_id",
        "commercial_matches",
        ["match_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_commercial_matches_match_run_id",
        table_name="commercial_matches",
    )
    op.drop_index(
        "ix_commercial_matches_tender_requirement_id",
        table_name="commercial_matches",
    )

    with op.batch_alter_table("commercial_matches") as batch_op:
        batch_op.drop_constraint(
            "fk_commercial_matches_match_run",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_commercial_matches_tender_requirement",
            type_="foreignkey",
        )

    op.drop_column("commercial_matches", "match_run_id")
    op.drop_column("commercial_matches", "tender_requirement_id")

    op.drop_index(
        "ix_commercial_match_runs_tender_analysis_id",
        table_name="commercial_match_runs",
    )
    op.drop_index(
        "ix_commercial_match_runs_commercial_analysis_id",
        table_name="commercial_match_runs",
    )
    op.drop_table("commercial_match_runs")
    op.drop_column("products", "technical_attributes")
