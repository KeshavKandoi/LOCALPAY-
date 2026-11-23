from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonObject = dict[str, Any]


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UpdatedAt:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Project(Base, CreatedAt, UpdatedAt):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_present"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


class ProjectRecord(CreatedAt):
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class ApiCredential(Base, ProjectRecord):
    __tablename__ = "api_credentials"
    __table_args__ = (
        CheckConstraint("key_id ~ '^lp_test_[0-9a-f]{32}$'", name="local_key"),
        ForeignKeyConstraint(
            ["project_id", "rotated_from_id"],
            ["api_credentials.project_id", "api_credentials.id"],
        ),
        UniqueConstraint("project_id", "rotated_from_id"),
        CheckConstraint("rotated_from_id <> id", name="rotation_predecessor"),
        CheckConstraint("octet_length(verifier) = 32", name="verifier_length"),
        CheckConstraint("char_length(btrim(label)) > 0", name="label_present"),
    )

    key_id: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    verifier: Mapped[bytes] = mapped_column(
        LargeBinary, deferred=True, deferred_raiseload=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[UUID | None] = mapped_column()

    @property
    def enabled(self) -> bool:
        return self.revoked_at is None


class Order(Base, ProjectRecord):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("project_id", "public_id"),
        UniqueConstraint("project_id", "receipt"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("amount_paid BETWEEN 0 AND amount", name="paid_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("status IN ('created', 'attempted', 'paid')", name="status"),
        Index("ix_orders_project_created_at", "project_id", "created_at"),
    )

    public_id: Mapped[str] = mapped_column(
        String(20),
        server_default=text(
            "'order_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 14)"
        ),
    )
    attempts: Mapped[int] = mapped_column(server_default="0")

    amount: Mapped[int] = mapped_column(BigInteger)
    amount_paid: Mapped[int] = mapped_column(BigInteger, server_default="0")
    amount_due: Mapped[int] = mapped_column(
        BigInteger, Computed("amount - amount_paid", persisted=True)
    )
    currency: Mapped[str] = mapped_column(String(3))
    receipt: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[JsonObject] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), server_default="created")


class Payment(Base, ProjectRecord, UpdatedAt):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("project_id", "public_id"),
        ForeignKeyConstraint(
            ["project_id", "order_id"], ["orders.project_id", "orders.id"]
        ),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(
            "amount_authorized BETWEEN amount_captured AND amount",
            name="authorized_amount",
        ),
        CheckConstraint("amount_captured BETWEEN 0 AND amount", name="captured_amount"),
        CheckConstraint(
            "amount_refunded BETWEEN 0 AND amount_captured", name="refunded_amount"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "status IN ('created', 'authorized', 'captured', 'refunded', 'failed')",
            name="status",
        ),
        Index("ix_payments_project_order", "project_id", "order_id"),
    )

    public_id: Mapped[str] = mapped_column(
        String(18),
        server_default=text(
            "'pay_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 14)"
        ),
    )
    capture_failure: Mapped[bool] = mapped_column(server_default=text("false"))
    order_id: Mapped[UUID] = mapped_column()
    amount: Mapped[int] = mapped_column(BigInteger)
    amount_authorized: Mapped[int] = mapped_column(BigInteger, server_default="0")
    amount_captured: Mapped[int] = mapped_column(BigInteger, server_default="0")
    amount_refunded: Mapped[int] = mapped_column(BigInteger, server_default="0")
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), server_default="created")
    method: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_description: Mapped[str | None] = mapped_column(String(255))


class Refund(Base, ProjectRecord, UpdatedAt):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("project_id", "public_id"),
        UniqueConstraint("project_id", "payment_id", "receipt"),
        UniqueConstraint("project_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["project_id", "payment_id"], ["payments.project_id", "payments.id"]
        ),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("status IN ('pending', 'processed', 'failed')", name="status"),
        Index("ix_refunds_project_payment", "project_id", "payment_id"),
    )

    public_id: Mapped[str] = mapped_column(
        String(19),
        server_default=text(
            "'rfnd_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 14)"
        ),
    )
    receipt: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[JsonObject] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    payment_id: Mapped[UUID] = mapped_column()
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")


class WebhookEndpoint(Base, ProjectRecord):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (UniqueConstraint("project_id", "url"),)

    url: Mapped[str] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    secret_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, deferred=True, deferred_raiseload=True
    )
    secret_reference: Mapped[str | None] = mapped_column(String(120))
    enabled_events: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )


class WebhookEvent(Base, ProjectRecord):
    __tablename__ = "webhook_events"
    __table_args__ = (
        Index("ix_webhook_events_project_created_at", "project_id", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[bytes] = mapped_column(LargeBinary)


class WebhookDelivery(Base, ProjectRecord):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["webhook_events.project_id", "webhook_events.id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "endpoint_id"],
            ["webhook_endpoints.project_id", "webhook_endpoints.id"],
        ),
        UniqueConstraint("project_id", "event_id", "endpoint_id"),
        Index("ix_webhook_deliveries_status_retry", "status", "next_retry_at"),
        Index("ix_webhook_deliveries_project_endpoint", "project_id", "endpoint_id"),
        CheckConstraint("attempt_count >= 0", name="attempt_count"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'delivered', 'failed')",
            name="status",
        ),
    )

    event_id: Mapped[UUID] = mapped_column()
    endpoint_id: Mapped[UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    next_retry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivery_metadata: Mapped[JsonObject] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


class WebhookDeliveryAttempt(Base, ProjectRecord):
    __tablename__ = "webhook_delivery_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "event_id"],
            ["webhook_events.project_id", "webhook_events.id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "endpoint_id"],
            ["webhook_endpoints.project_id", "webhook_endpoints.id"],
        ),
        UniqueConstraint("project_id", "endpoint_id", "event_id", "attempt_number"),
        Index("ix_webhook_attempts_project_event", "project_id", "event_id"),
        CheckConstraint("attempt_number > 0", name="positive_attempt"),
        CheckConstraint("http_status BETWEEN 100 AND 599", name="http_status"),
        CheckConstraint("duration_ms >= 0", name="duration"),
    )

    event_id: Mapped[UUID] = mapped_column()
    endpoint_id: Mapped[UUID] = mapped_column()
    attempt_number: Mapped[int] = mapped_column()
    http_status: Mapped[int | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(120))


class SimulationScenario(Base, ProjectRecord):
    __tablename__ = "simulation_scenarios"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    name: Mapped[str] = mapped_column(String(120))
    scenario_type: Mapped[str] = mapped_column(String(120), server_default="custom")
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    configuration: Mapped[JsonObject] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


class ReliabilityTestRun(Base, ProjectRecord):
    __tablename__ = "reliability_test_runs"
    __table_args__ = (
        Index("ix_reliability_runs_project_created_at", "project_id", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'error', 'inconclusive')",
            name="status",
        ),
    )

    suite_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[JsonObject | None] = mapped_column(JSONB(none_as_null=True))


class ScenarioExecution(Base, ProjectRecord):
    __tablename__ = "scenario_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "scenario_id"],
            ["simulation_scenarios.project_id", "simulation_scenarios.id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "test_run_id"],
            ["reliability_test_runs.project_id", "reliability_test_runs.id"],
        ),
        Index("ix_scenario_executions_project_scenario", "project_id", "scenario_id"),
        Index("ix_scenario_executions_project_run", "project_id", "test_run_id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')", name="status"
        ),
    )

    scenario_id: Mapped[UUID] = mapped_column()
    test_run_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[JsonObject | None] = mapped_column(JSONB(none_as_null=True))


class AuditRecord(Base, ProjectRecord):
    __tablename__ = "audit_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "credential_id"],
            ["api_credentials.project_id", "api_credentials.id"],
        ),
        Index("ix_audit_records_project_created_at", "project_id", "created_at"),
        Index("ix_audit_records_project_credential", "project_id", "credential_id"),
    )

    credential_id: Mapped[UUID | None] = mapped_column()
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(Text)
