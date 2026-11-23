import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_refund_contract"
down_revision = "0005_payment_simulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refunds",
        sa.Column(
            "public_id",
            sa.String(19),
            nullable=False,
            server_default=sa.text(
                "'rfnd_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 14)"
            ),
        ),
    )
    op.add_column("refunds", sa.Column("receipt", sa.String(40)))
    op.add_column(
        "refunds",
        sa.Column(
            "notes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("refunds", sa.Column("idempotency_key", sa.String(128)))
    op.add_column("refunds", sa.Column("request_fingerprint", sa.String(64)))
    op.create_unique_constraint(
        op.f("uq_refunds_project_id_public_id"), "refunds", ["project_id", "public_id"]
    )
    op.create_unique_constraint(
        op.f("uq_refunds_project_id_payment_id_receipt"),
        "refunds",
        ["project_id", "payment_id", "receipt"],
    )
    op.create_unique_constraint(
        op.f("uq_refunds_project_id_idempotency_key"),
        "refunds",
        ["project_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_refunds_project_id_idempotency_key"), "refunds", type_="unique"
    )
    op.drop_constraint(
        op.f("uq_refunds_project_id_payment_id_receipt"), "refunds", type_="unique"
    )
    op.drop_constraint(
        op.f("uq_refunds_project_id_public_id"), "refunds", type_="unique"
    )
    for column in (
        "request_fingerprint",
        "idempotency_key",
        "notes",
        "receipt",
        "public_id",
    ):
        op.drop_column("refunds", column)
