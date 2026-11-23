import sqlalchemy as sa

from alembic import op

revision = "0004_order_contract"
down_revision = "0003_rotation_and_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "public_id",
            sa.String(20),
            nullable=False,
            server_default=sa.text(
                "'order_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 14)"
            ),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(op.f("ck_orders_attempts"), "orders", "attempts >= 0")
    op.create_unique_constraint(
        op.f("uq_orders_project_id_public_id"), "orders", ["project_id", "public_id"]
    )
    op.create_unique_constraint(
        op.f("uq_orders_project_id_receipt"), "orders", ["project_id", "receipt"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_orders_project_id_receipt"), "orders", type_="unique")
    op.drop_constraint(op.f("uq_orders_project_id_public_id"), "orders", type_="unique")
    op.drop_constraint(op.f("ck_orders_attempts"), "orders", type_="check")
    op.drop_column("orders", "attempts")
    op.drop_column("orders", "public_id")
