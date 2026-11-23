import sqlalchemy as sa

from alembic import op

revision = "0007_webhook_storage"
down_revision = "0006_refund_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_endpoints", sa.Column("secret_ciphertext", sa.LargeBinary()))
    op.execute(
        "CREATE FUNCTION reject_webhook_event_update() RETURNS trigger LANGUAGE plpgsql "
        "AS $$ BEGIN RAISE EXCEPTION 'Webhook events are immutable' USING ERRCODE = '23514'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER immutable_webhook_events BEFORE UPDATE ON webhook_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_webhook_event_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER immutable_webhook_events ON webhook_events")
    op.execute("DROP FUNCTION reject_webhook_event_update()")
    op.drop_column("webhook_endpoints", "secret_ciphertext")
