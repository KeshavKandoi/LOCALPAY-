from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_rotation_and_models"
down_revision: str | Sequence[str] | None = "0002_project_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "delivery_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'delivered', 'failed')",
            name=op.f("ck_webhook_deliveries_status"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_webhook_deliveries_attempt_count")
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "endpoint_id"],
            ["webhook_endpoints.project_id", "webhook_endpoints.id"],
            name=op.f("fk_webhook_deliveries_project_id_endpoint_id_webhook_endpoints"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["webhook_events.project_id", "webhook_events.id"],
            name=op.f("fk_webhook_deliveries_project_id_event_id_webhook_events"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_webhook_deliveries_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint(
            "project_id",
            "event_id",
            "endpoint_id",
            name=op.f("uq_webhook_deliveries_project_id_event_id_endpoint_id"),
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_project_endpoint",
        "webhook_deliveries",
        ["project_id", "endpoint_id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_deliveries_status_retry",
        "webhook_deliveries",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.add_column(
        "api_credentials", sa.Column("rotated_from_id", sa.Uuid(), nullable=True)
    )
    op.create_unique_constraint(
        op.f("uq_api_credentials_project_id_rotated_from_id"),
        "api_credentials",
        ["project_id", "rotated_from_id"],
    )
    op.create_foreign_key(
        op.f("fk_api_credentials_project_id_rotated_from_id_api_credentials"),
        "api_credentials",
        "api_credentials",
        ["project_id", "rotated_from_id"],
        ["project_id", "id"],
    )
    op.add_column(
        "orders",
        sa.Column(
            "amount_due",
            sa.BigInteger(),
            sa.Computed("amount - amount_paid", persisted=True),
            nullable=False,
        ),
    )
    op.add_column(
        "payments",
        sa.Column(
            "amount_authorized", sa.BigInteger(), server_default="0", nullable=False
        ),
    )
    op.add_column("payments", sa.Column("method", sa.String(length=32), nullable=True))
    op.add_column(
        "payments", sa.Column("error_description", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "payments",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("refunds", sa.Column("currency", sa.String(length=3), nullable=True))
    op.execute(
        "UPDATE refunds AS refund SET currency = payment.currency FROM payments AS payment "
        "WHERE refund.project_id = payment.project_id AND refund.payment_id = payment.id"
    )
    op.alter_column("refunds", "currency", nullable=False)
    op.add_column("refunds", sa.Column("reason", sa.String(length=255), nullable=True))
    op.add_column(
        "refunds",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "reliability_test_runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "simulation_scenarios",
        sa.Column(
            "scenario_type",
            sa.String(length=120),
            server_default="custom",
            nullable=False,
        ),
    )
    op.add_column(
        "simulation_scenarios",
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.add_column(
        "webhook_endpoints",
        sa.Column("secret_reference", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "webhook_endpoints",
        sa.Column(
            "enabled_events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    op.execute(
        "UPDATE payments SET amount_authorized = amount_captured WHERE amount_captured > 0"
    )
    op.create_check_constraint(
        op.f("ck_payments_authorized_amount"),
        "payments",
        "amount_authorized BETWEEN amount_captured AND amount",
    )
    op.create_check_constraint(
        op.f("ck_projects_status"), "projects", "status IN ('active', 'disabled')"
    )
    op.create_check_constraint(
        op.f("ck_refunds_currency_format"), "refunds", "currency ~ '^[A-Z]{3}$'"
    )
    op.create_check_constraint(
        op.f("ck_api_credentials_rotation_predecessor"),
        "api_credentials",
        "rotated_from_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_api_credentials_rotation_predecessor"),
        "api_credentials",
        type_="check",
    )
    op.drop_constraint(op.f("ck_refunds_currency_format"), "refunds", type_="check")
    op.drop_constraint(op.f("ck_projects_status"), "projects", type_="check")
    op.drop_constraint(op.f("ck_payments_authorized_amount"), "payments", type_="check")
    op.drop_column("webhook_endpoints", "enabled_events")
    op.drop_column("webhook_endpoints", "secret_reference")
    op.drop_column("simulation_scenarios", "enabled")
    op.drop_column("simulation_scenarios", "scenario_type")
    op.drop_column("reliability_test_runs", "started_at")
    op.drop_column("refunds", "updated_at")
    op.drop_column("refunds", "reason")
    op.drop_column("refunds", "currency")
    op.drop_column("projects", "updated_at")
    op.drop_column("projects", "status")
    op.drop_column("payments", "updated_at")
    op.drop_column("payments", "error_description")
    op.drop_column("payments", "method")
    op.drop_column("payments", "amount_authorized")
    op.drop_column("orders", "amount_due")
    op.drop_constraint(
        op.f("fk_api_credentials_project_id_rotated_from_id_api_credentials"),
        "api_credentials",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_api_credentials_project_id_rotated_from_id"),
        "api_credentials",
        type_="unique",
    )
    op.drop_column("api_credentials", "rotated_from_id")
    op.drop_index("ix_webhook_deliveries_status_retry", table_name="webhook_deliveries")
    op.drop_index(
        "ix_webhook_deliveries_project_endpoint", table_name="webhook_deliveries"
    )
    op.drop_table("webhook_deliveries")
