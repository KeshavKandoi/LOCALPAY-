import sqlalchemy as sa

from alembic import op

revision = "0008_delivery_leases"
down_revision = "0007_webhook_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_deliveries", sa.Column("lease_token", sa.Uuid()))
    op.add_column(
        "webhook_deliveries", sa.Column("leased_until", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("webhook_deliveries", "leased_until")
    op.drop_column("webhook_deliveries", "lease_token")
