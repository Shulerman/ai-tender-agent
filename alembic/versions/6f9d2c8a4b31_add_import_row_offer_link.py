"""Add offer link to imported price-list rows."""

from alembic import op
import sqlalchemy as sa


revision = "6f9d2c8a4b31"
down_revision = "b7c4e9a1d602"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_list_import_rows") as batch_op:
        batch_op.add_column(
            sa.Column("offer_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_price_list_import_rows_offer_id_supplier_offers",
            "supplier_offers",
            ["offer_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_price_list_import_rows_offer_id",
            ["offer_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("price_list_import_rows") as batch_op:
        batch_op.drop_index("ix_price_list_import_rows_offer_id")
        batch_op.drop_constraint(
            "fk_price_list_import_rows_offer_id_supplier_offers",
            type_="foreignkey",
        )
        batch_op.drop_column("offer_id")
