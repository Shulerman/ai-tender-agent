"""Add independent semantic validation status.

Revision ID: b7c4e9a1d602
Revises: 28d979223ef8
Create Date: 2026-11-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c4e9a1d602"
down_revision: Union[str, Sequence[str], None] = "28d979223ef8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tender_analyses",
        sa.Column(
            "semantic_validation_status",
            sa.String(length=30),
            nullable=False,
            server_default="Не запускалась",
        ),
    )


def downgrade() -> None:
    op.drop_column("tender_analyses", "semantic_validation_status")
