import sqlalchemy as sa

from alembic import op

revision = "0009_chaos_delivery"
down_revision = "0008_delivery_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_deliveries", sa.Column("execution_id", sa.Uuid()))
    op.add_column("webhook_deliveries", sa.Column("after_delivery_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_webhook_deliveries_project_id_execution_id_scenario_executions"),
        "webhook_deliveries",
        "scenario_executions",
        ["project_id", "execution_id"],
        ["project_id", "id"],
    )
    op.create_foreign_key(
        op.f("fk_webhook_deliveries_project_id_after_delivery_id_webhook_deliveries"),
        "webhook_deliveries",
        "webhook_deliveries",
        ["project_id", "after_delivery_id"],
        ["project_id", "id"],
    )
    op.create_index(
        "ix_webhook_deliveries_project_execution",
        "webhook_deliveries",
        ["project_id", "execution_id"],
    )
    op.create_index(
        "ix_webhook_deliveries_project_predecessor",
        "webhook_deliveries",
        ["project_id", "after_delivery_id"],
    )
    op.create_index(
        "uq_webhook_deliveries_regular",
        "webhook_deliveries",
        ["project_id", "event_id", "endpoint_id"],
        unique=True,
        postgresql_where=sa.text("execution_id IS NULL"),
    )
    op.drop_constraint(
        op.f("uq_webhook_deliveries_project_id_event_id_endpoint_id"),
        "webhook_deliveries",
        type_="unique",
    )
    op.add_column("webhook_delivery_attempts", sa.Column("delivery_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_webhook_delivery_attempts_project_id_delivery_id_webhook_deliveries"),
        "webhook_delivery_attempts",
        "webhook_deliveries",
        ["project_id", "delivery_id"],
        ["project_id", "id"],
    )
    op.execute(
        "UPDATE webhook_delivery_attempts AS attempt SET delivery_id = delivery.id "
        "FROM webhook_deliveries AS delivery WHERE attempt.project_id = delivery.project_id "
        "AND attempt.event_id = delivery.event_id AND attempt.endpoint_id = delivery.endpoint_id"
    )
    op.create_unique_constraint(
        op.f("uq_webhook_delivery_attempts_project_id_delivery_id_attempt_number"),
        "webhook_delivery_attempts",
        ["project_id", "delivery_id", "attempt_number"],
    )
    op.create_index(
        "uq_webhook_attempts_legacy",
        "webhook_delivery_attempts",
        ["project_id", "endpoint_id", "event_id", "attempt_number"],
        unique=True,
        postgresql_where=sa.text("delivery_id IS NULL"),
    )
    op.drop_constraint(
        op.f(
            "uq_webhook_delivery_attempts_project_id_endpoint_id_event_id_attempt_number"
        ),
        "webhook_delivery_attempts",
        type_="unique",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM webhook_deliveries WHERE execution_id IS NOT NULL) "
        "THEN RAISE EXCEPTION 'Cannot downgrade stored webhook chaos executions'; END IF; END; $$"
    )
    op.create_unique_constraint(
        op.f(
            "uq_webhook_delivery_attempts_project_id_endpoint_id_event_id_attempt_number"
        ),
        "webhook_delivery_attempts",
        ["project_id", "endpoint_id", "event_id", "attempt_number"],
    )
    op.drop_index("uq_webhook_attempts_legacy", table_name="webhook_delivery_attempts")
    op.drop_constraint(
        op.f("uq_webhook_delivery_attempts_project_id_delivery_id_attempt_number"),
        "webhook_delivery_attempts",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_webhook_delivery_attempts_project_id_delivery_id_webhook_deliveries"),
        "webhook_delivery_attempts",
        type_="foreignkey",
    )
    op.drop_column("webhook_delivery_attempts", "delivery_id")
    op.create_unique_constraint(
        op.f("uq_webhook_deliveries_project_id_event_id_endpoint_id"),
        "webhook_deliveries",
        ["project_id", "event_id", "endpoint_id"],
    )
    op.drop_index("uq_webhook_deliveries_regular", table_name="webhook_deliveries")
    op.drop_index(
        "ix_webhook_deliveries_project_predecessor", table_name="webhook_deliveries"
    )
    op.drop_index(
        "ix_webhook_deliveries_project_execution", table_name="webhook_deliveries"
    )
    op.drop_constraint(
        op.f("fk_webhook_deliveries_project_id_after_delivery_id_webhook_deliveries"),
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_webhook_deliveries_project_id_execution_id_scenario_executions"),
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_column("webhook_deliveries", "after_delivery_id")
    op.drop_column("webhook_deliveries", "execution_id")
