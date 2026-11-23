from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_project_models"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_projects_slug_format")
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) > 0", name=op.f("ck_projects_name_present")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("slug", name=op.f("uq_projects_slug")),
    )
    op.create_table(
        "api_credentials",
        sa.Column("key_id", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("verifier", sa.LargeBinary(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "key_id ~ '^lp_test_[0-9a-f]{32}$'",
            name=op.f("ck_api_credentials_local_key"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(label)) > 0",
            name=op.f("ck_api_credentials_label_present"),
        ),
        sa.CheckConstraint(
            "octet_length(verifier) = 32",
            name=op.f("ck_api_credentials_verifier_length"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_api_credentials_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_api_credentials")),
        sa.UniqueConstraint("key_id", name=op.f("uq_api_credentials_key_id")),
    )
    op.create_table(
        "orders",
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("amount_paid", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("receipt", sa.String(length=40), nullable=True),
        sa.Column(
            "notes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="created", nullable=False
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
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_orders_currency_format")
        ),
        sa.CheckConstraint(
            "status IN ('created', 'attempted', 'paid')", name=op.f("ck_orders_status")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_orders_positive_amount")),
        sa.CheckConstraint(
            "amount_paid BETWEEN 0 AND amount", name=op.f("ck_orders_paid_amount")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_orders_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_orders")),
    )
    op.create_index(
        "ix_orders_project_created_at",
        "orders",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "reliability_test_runs",
        sa.Column("suite_name", sa.String(length=120), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
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
            "status IN ('pending', 'running', 'passed', 'failed', 'error', 'inconclusive')",
            name=op.f("ck_reliability_test_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_reliability_test_runs_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint(
            "project_id", "id", name=op.f("pk_reliability_test_runs")
        ),
    )
    op.create_index(
        "ix_reliability_runs_project_created_at",
        "reliability_test_runs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "simulation_scenarios",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "configuration",
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
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_simulation_scenarios_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint(
            "project_id", "id", name=op.f("pk_simulation_scenarios")
        ),
        sa.UniqueConstraint(
            "project_id", "name", name=op.f("uq_simulation_scenarios_project_id_name")
        ),
    )
    op.create_table(
        "webhook_endpoints",
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_webhook_endpoints_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_webhook_endpoints")),
        sa.UniqueConstraint(
            "project_id", "url", name=op.f("uq_webhook_endpoints_project_id_url")
        ),
    )
    op.create_table(
        "webhook_events",
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_webhook_events_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_webhook_events")),
    )
    op.create_index(
        "ix_webhook_events_project_created_at",
        "webhook_events",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "audit_records",
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "credential_id"],
            ["api_credentials.project_id", "api_credentials.id"],
            name=op.f("fk_audit_records_project_id_credential_id_api_credentials"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_audit_records_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_audit_records")),
    )
    op.create_index(
        "ix_audit_records_project_created_at",
        "audit_records",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_records_project_credential",
        "audit_records",
        ["project_id", "credential_id"],
        unique=False,
    )
    op.create_table(
        "payments",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "amount_captured", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "amount_refunded", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="created", nullable=False
        ),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_payments_currency_format")
        ),
        sa.CheckConstraint(
            "status IN ('created', 'authorized', 'captured', 'refunded', 'failed')",
            name=op.f("ck_payments_status"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_positive_amount")),
        sa.CheckConstraint(
            "amount_captured BETWEEN 0 AND amount",
            name=op.f("ck_payments_captured_amount"),
        ),
        sa.CheckConstraint(
            "amount_refunded BETWEEN 0 AND amount_captured",
            name=op.f("ck_payments_refunded_amount"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "order_id"],
            ["orders.project_id", "orders.id"],
            name=op.f("fk_payments_project_id_order_id_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_payments_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_payments")),
    )
    op.create_index(
        "ix_payments_project_order",
        "payments",
        ["project_id", "order_id"],
        unique=False,
    )
    op.create_table(
        "scenario_executions",
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
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
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name=op.f("ck_scenario_executions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "scenario_id"],
            ["simulation_scenarios.project_id", "simulation_scenarios.id"],
            name=op.f(
                "fk_scenario_executions_project_id_scenario_id_simulation_scenarios"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "test_run_id"],
            ["reliability_test_runs.project_id", "reliability_test_runs.id"],
            name=op.f(
                "fk_scenario_executions_project_id_test_run_id_reliability_test_runs"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_scenario_executions_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint(
            "project_id", "id", name=op.f("pk_scenario_executions")
        ),
    )
    op.create_index(
        "ix_scenario_executions_project_run",
        "scenario_executions",
        ["project_id", "test_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_scenario_executions_project_scenario",
        "scenario_executions",
        ["project_id", "scenario_id"],
        unique=False,
    )
    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name=op.f("ck_webhook_delivery_attempts_positive_attempt"),
        ),
        sa.CheckConstraint(
            "duration_ms >= 0", name=op.f("ck_webhook_delivery_attempts_duration")
        ),
        sa.CheckConstraint(
            "http_status BETWEEN 100 AND 599",
            name=op.f("ck_webhook_delivery_attempts_http_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "endpoint_id"],
            ["webhook_endpoints.project_id", "webhook_endpoints.id"],
            name=op.f(
                "fk_webhook_delivery_attempts_project_id_endpoint_id_webhook_endpoints"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["webhook_events.project_id", "webhook_events.id"],
            name=op.f(
                "fk_webhook_delivery_attempts_project_id_event_id_webhook_events"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_webhook_delivery_attempts_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint(
            "project_id", "id", name=op.f("pk_webhook_delivery_attempts")
        ),
        sa.UniqueConstraint(
            "project_id",
            "endpoint_id",
            "event_id",
            "attempt_number",
            name=op.f(
                "uq_webhook_delivery_attempts_project_id_endpoint_id_event_id_attempt_number"
            ),
        ),
    )
    op.create_index(
        "ix_webhook_attempts_project_event",
        "webhook_delivery_attempts",
        ["project_id", "event_id"],
        unique=False,
    )
    op.create_table(
        "refunds",
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
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
            "status IN ('pending', 'processed', 'failed')",
            name=op.f("ck_refunds_status"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_refunds_positive_amount")),
        sa.ForeignKeyConstraint(
            ["project_id", "payment_id"],
            ["payments.project_id", "payments.id"],
            name=op.f("fk_refunds_project_id_payment_id_payments"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_refunds_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_refunds")),
    )
    op.create_index(
        "ix_refunds_project_payment",
        "refunds",
        ["project_id", "payment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_refunds_project_payment", table_name="refunds")
    op.drop_table("refunds")
    op.drop_index(
        "ix_webhook_attempts_project_event", table_name="webhook_delivery_attempts"
    )
    op.drop_table("webhook_delivery_attempts")
    op.drop_index(
        "ix_scenario_executions_project_scenario", table_name="scenario_executions"
    )
    op.drop_index(
        "ix_scenario_executions_project_run", table_name="scenario_executions"
    )
    op.drop_table("scenario_executions")
    op.drop_index("ix_payments_project_order", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_audit_records_project_credential", table_name="audit_records")
    op.drop_index("ix_audit_records_project_created_at", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_webhook_events_project_created_at", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_table("webhook_endpoints")
    op.drop_table("simulation_scenarios")
    op.drop_index(
        "ix_reliability_runs_project_created_at", table_name="reliability_test_runs"
    )
    op.drop_table("reliability_test_runs")
    op.drop_index("ix_orders_project_created_at", table_name="orders")
    op.drop_table("orders")
    op.drop_table("api_credentials")
    op.drop_table("projects")
