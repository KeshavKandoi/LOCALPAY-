from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import DatabaseSession, require_admin
from app.api.projects import ShortName, get_project
from app.models import (
    JsonObject,
    ScenarioExecution,
    SimulationScenario,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.webhook_chaos import WebhookChaos, enqueue_chaos

chaos_router = APIRouter(
    prefix="/localpay/admin/v1/projects/{project_id}",
    tags=["LocalPay webhook chaos"],
    dependencies=[Depends(require_admin)],
)


class ChaosCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ShortName
    type: Literal["webhook.chaos"] = "webhook.chaos"
    config: WebhookChaos


class StartChaos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_id: UUID
    event_ids: Annotated[set[UUID], Field(min_length=1, max_length=32)]


class ScenarioView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    scenario_type: str
    enabled: bool
    configuration: WebhookChaos


class ExecutionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scenario_id: UUID
    status: str
    created_at: datetime
    finished_at: datetime | None
    result: JsonObject | None


@chaos_router.post("/webhook-scenarios", status_code=201)
def add_scenario(
    project_id: UUID, body: ChaosCreate, session: DatabaseSession
) -> ScenarioView:
    try:
        with session.begin():
            get_project(session, project_id)
            scenario = SimulationScenario(
                project_id=project_id,
                name=body.name,
                scenario_type=body.type,
                configuration=body.config.model_dump(),
            )
            session.add(scenario)
            session.flush()
            return ScenarioView.model_validate(scenario)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(409) from None
        raise


@chaos_router.get("/webhook-scenarios")
def get_scenarios(project_id: UUID, session: DatabaseSession) -> list[ScenarioView]:
    rows = session.scalars(
        select(SimulationScenario)
        .where(
            SimulationScenario.project_id == project_id,
            SimulationScenario.scenario_type == "webhook.chaos",
        )
        .order_by(SimulationScenario.name)
    )
    return [ScenarioView.model_validate(row) for row in rows]


@chaos_router.post("/webhook-scenarios/{scenario_id}/runs", status_code=201)
def run_scenario(
    project_id: UUID,
    scenario_id: UUID,
    body: StartChaos,
    session: DatabaseSession,
) -> ExecutionView:
    with session.begin():
        scenario = session.get(SimulationScenario, (project_id, scenario_id))
        endpoint = session.get(WebhookEndpoint, (project_id, body.endpoint_id))
        rows = session.scalars(
            select(WebhookEvent).where(
                WebhookEvent.project_id == project_id,
                WebhookEvent.id.in_(body.event_ids),
            )
        )
        events = list(rows)
        if (
            scenario is None
            or not scenario.enabled
            or scenario.scenario_type != "webhook.chaos"
            or endpoint is None
            or not endpoint.enabled
            or len(events) != len(body.event_ids)
        ):
            raise HTTPException(404)
        try:
            execution = enqueue_chaos(session, project_id, scenario, endpoint, events)
        except ValueError as exc:
            raise HTTPException(422) from exc
        return ExecutionView.model_validate(execution)


@chaos_router.get("/webhook-runs/{execution_id}")
def get_execution(
    project_id: UUID,
    execution_id: UUID,
    session: DatabaseSession,
) -> ExecutionView:
    execution = session.get(ScenarioExecution, (project_id, execution_id))
    if execution is None:
        raise HTTPException(404)
    return ExecutionView.model_validate(execution)


class RunDelivery(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    endpoint_id: UUID
    status: str
    attempt_count: int
    next_retry_at: datetime
    delivery_metadata: JsonObject


@chaos_router.get("/webhook-runs/{execution_id}/deliveries")
def get_execution_deliveries(
    project_id: UUID,
    execution_id: UUID,
    session: DatabaseSession,
) -> list[RunDelivery]:
    if session.get(ScenarioExecution, (project_id, execution_id)) is None:
        raise HTTPException(404)
    rows = session.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.project_id == project_id,
            WebhookDelivery.execution_id == execution_id,
        )
    )
    return sorted(
        (RunDelivery.model_validate(row) for row in rows),
        key=lambda row: int(row.delivery_metadata["sequence"]),
    )
