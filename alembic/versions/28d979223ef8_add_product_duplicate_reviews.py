"""Add product duplicate reviews.

Revision ID: 28d979223ef8
Revises: a31f8c9d2e74
Create Date: 2026-11-23 17:34:15.405421
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "28d979223ef8"
down_revision: Union[str, Sequence[str], None] = "a31f8c9d2e74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_duplicate_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id_1", sa.Integer(), nullable=False),
        sa.Column("product_id_2", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "product_id_1 < product_id_2",
            name="ck_product_duplicate_review_order",
        ),
        sa.ForeignKeyConstraint(
            ["product_id_1"],
            ["products.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id_2"],
            ["products.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id_1",
            "product_id_2",
            name="uq_product_duplicate_review_pair",
        ),
    )
    op.create_index(
        "ix_product_duplicate_reviews_product_id_2",
        "product_duplicate_reviews",
        ["product_id_2"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_duplicate_reviews_product_id_2",
        table_name="product_duplicate_reviews",
    )
    op.drop_table("product_duplicate_reviews")
