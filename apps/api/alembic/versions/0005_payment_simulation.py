import sqlalchemy as sa

from alembic import op

revision = "0005_payment_simulation"
down_revision = "0004_order_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "public_id",
            sa.String(18),
            nullable=False,
            server_default=sa.text(
                "'pay_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 14)"
            ),
        ),
    )
    op.add_column(
        "payments",
        sa.Column(
            "capture_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_unique_constraint(
        op.f("uq_payments_project_id_public_id"),
        "payments",
        ["project_id", "public_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_payments_project_id_public_id"), "payments", type_="unique"
    )
    op.drop_column("payments", "capture_failure")
    op.drop_column("payments", "public_id")
