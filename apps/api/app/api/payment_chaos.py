from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select

from app.api.auth import DatabaseSession, require_admin
from app.api.projects import get_project
from app.api.webhook_chaos import ExecutionView
from app.models import ScenarioExecution, SimulationScenario
from app.services.payment_chaos import (
    FAULT_CODES,
    ChaosConflict,
    PaymentChaosType,
    arm_gateway_fault,
    cancel_gateway_fault,
    create_execution,
    execute_transaction_case,
    expire_gateway_faults,
    finish_payment_execution,
)

payment_chaos_router = APIRouter(
    prefix="/localpay/admin/v1/projects/{project_id}/payment-chaos",
    tags=["LocalPay payment chaos"],
    dependencies=[Depends(require_admin)],
)


class StartPaymentChaos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: PaymentChaosType
    amount: Annotated[int, Field(strict=True, ge=100, le=1_000_000_000)] = 600
    requests: Annotated[int, Field(strict=True, ge=1, le=10)] = 1
    delay_ms: Annotated[int, Field(strict=True, ge=0, le=2000)] = 50


@payment_chaos_router.get("/scenarios")
def get_cases() -> list[PaymentChaosType]:
    return list(PaymentChaosType)


@payment_chaos_router.post("/runs", status_code=201)
def run_case(
    project_id: UUID,
    body: StartPaymentChaos,
    request: Request,
    session: DatabaseSession,
) -> ExecutionView:
    try:
        with session.begin():
            execution = create_execution(session, project_id, body.type)
            execution_id = execution.id
            if code := FAULT_CODES.get(body.type):
                arm_gateway_fault(session, execution, code, body.requests)
                return ExecutionView.model_validate(execution)
    except LookupError:
        raise HTTPException(404) from None
    except ChaosConflict:
        raise HTTPException(409) from None
    engine: Engine = request.app.state.engine
    try:
        evidence = execute_transaction_case(
            engine, project_id, execution_id, body.type, body.amount, body.delay_ms
        )
    except Exception as exc:
        with session.begin():
            finish_payment_execution(
                session,
                project_id,
                execution_id,
                {"passed": False, "error_type": type(exc).__name__},
            )
        raise
    with session.begin():
        finish_payment_execution(session, project_id, execution_id, evidence)
        completed = session.get(ScenarioExecution, (project_id, execution_id))
        return ExecutionView.model_validate(completed)


class PaymentRunView(ExecutionView):
    scenario_type: PaymentChaosType


@payment_chaos_router.get("/runs")
def list_cases(
    project_id: UUID,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PaymentRunView]:
    get_project(session, project_id)
    expire_gateway_faults(session, project_id=project_id)
    session.commit()
    rows = session.execute(
        select(ScenarioExecution, SimulationScenario.scenario_type)
        .join(
            SimulationScenario,
            (SimulationScenario.project_id == ScenarioExecution.project_id)
            & (SimulationScenario.id == ScenarioExecution.scenario_id),
        )
        .where(
            ScenarioExecution.project_id == project_id,
            SimulationScenario.scenario_type.in_(list(PaymentChaosType)),
        )
        .order_by(ScenarioExecution.created_at.desc(), ScenarioExecution.id)
        .limit(count)
    )
    return [
        PaymentRunView(
            **ExecutionView.model_validate(execution).model_dump(),
            scenario_type=PaymentChaosType(scenario_type),
        )
        for execution, scenario_type in rows
    ]


@payment_chaos_router.get("/runs/{execution_id}")
def get_case(
    project_id: UUID,
    execution_id: UUID,
    session: DatabaseSession,
) -> ExecutionView:
    expire_gateway_faults(session, project_id=project_id, execution_id=execution_id)
    session.commit()
    execution = session.scalar(
        select(ScenarioExecution)
        .join(
            SimulationScenario,
            (SimulationScenario.project_id == ScenarioExecution.project_id)
            & (SimulationScenario.id == ScenarioExecution.scenario_id),
        )
        .where(
            ScenarioExecution.project_id == project_id,
            ScenarioExecution.id == execution_id,
            SimulationScenario.scenario_type.in_(list(PaymentChaosType)),
        )
    )
    if execution is None:
        raise HTTPException(404)
    return ExecutionView.model_validate(execution)


@payment_chaos_router.post("/runs/{execution_id}/cancel", status_code=204)
def cancel_case(project_id: UUID, execution_id: UUID, session: DatabaseSession) -> None:
    with session.begin():
        if not cancel_gateway_fault(session, project_id, execution_id):
            raise HTTPException(404)
