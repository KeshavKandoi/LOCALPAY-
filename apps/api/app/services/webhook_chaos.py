from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ScenarioExecution,
    SimulationScenario,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)


class WebhookChaos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delay_ms: Annotated[int, Field(strict=True, ge=0, le=60000)] = 0
    duplicate_count: Annotated[int, Field(strict=True, ge=1, le=32)] = 1
    reorder_events: bool = Field(default=False, strict=True)
    burst_interval_ms: Annotated[int, Field(strict=True, ge=0, le=1000)] = 0
    failure_mode: Annotated[
        str,
        Field(
            pattern=r"^(none|http_500|http_429|timeout|reset|unavailable|invalid_signature|worker_interruption)$"
        ),
    ] = "none"
    failure_attempts: Annotated[int, Field(strict=True, ge=1, le=10)] = 1
    retry_limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 5

    @model_validator(mode="after")
    def validate_mode(self) -> "WebhookChaos":
        if self.failure_mode != "none" and self.failure_attempts > self.retry_limit:
            raise ValueError("Failure attempts cannot exceed retry limit")
        return self


def enqueue_chaos(
    session: Session,
    project_id: UUID,
    scenario: SimulationScenario,
    endpoint: WebhookEndpoint,
    events: list[WebhookEvent],
) -> ScenarioExecution:
    config = WebhookChaos.model_validate(scenario.configuration)
    if config.reorder_events and len(events) < 2:
        raise ValueError("Reordering requires at least two events")
    if len(events) * config.duplicate_count > 64:
        raise ValueError("At most 64 deliveries may be scheduled per execution")
    if any(event.event_type not in endpoint.enabled_events for event in events):
        raise ValueError("Endpoint must subscribe to every selected event")
    ordered = sorted(
        events,
        key=lambda event: (event.created_at, event.id),
        reverse=config.reorder_events,
    )
    now = datetime.now(UTC)
    execution = ScenarioExecution(
        project_id=project_id,
        scenario_id=scenario.id,
        status="running",
        result={
            "configuration": config.model_dump(),
            "event_ids": [str(event.id) for event in ordered],
        },
    )
    session.add(execution)
    session.flush()
    predecessor: UUID | None = None
    index = 0
    for event in ordered:
        for _ in range(config.duplicate_count):
            delivery_id = uuid4()
            session.add(
                WebhookDelivery(
                    id=delivery_id,
                    project_id=project_id,
                    event_id=event.id,
                    endpoint_id=endpoint.id,
                    execution_id=execution.id,
                    after_delivery_id=predecessor if config.reorder_events else None,
                    next_retry_at=now
                    + timedelta(
                        milliseconds=config.delay_ms + index * config.burst_interval_ms
                    ),
                    delivery_metadata={
                        "failure_mode": config.failure_mode,
                        "failure_attempts": config.failure_attempts,
                        "retry_limit": config.retry_limit,
                        "sequence": index + 1,
                    },
                )
            )
            session.flush()
            predecessor = delivery_id
            index += 1
    return execution


def update_execution(
    session: Session, delivery: WebhookDelivery, now: datetime
) -> None:
    if delivery.execution_id is None:
        return
    execution = session.get(
        ScenarioExecution,
        (delivery.project_id, delivery.execution_id),
        with_for_update=True,
    )
    if execution is None:
        raise RuntimeError("Webhook chaos execution is missing")
    session.flush()
    states = session.scalars(
        select(WebhookDelivery.status).where(
            WebhookDelivery.project_id == delivery.project_id,
            WebhookDelivery.execution_id == delivery.execution_id,
        )
    ).all()
    if all(state in {"delivered", "failed"} for state in states):
        execution.status = "failed" if "failed" in states else "succeeded"
        execution.finished_at = now
        execution.result = {
            **(execution.result or {}),
            "delivered": states.count("delivered"),
            "failed": states.count("failed"),
        }
