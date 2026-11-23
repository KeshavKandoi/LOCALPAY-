from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select

from app.api.auth import DatabaseSession, require_admin
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
            execution.result = {
                **(execution.result or {}),
                "error_type": type(exc).__name__,
            }
            execution.status = "failed"
            execution.finished_at = datetime.now(UTC)
        raise
    with session.begin():
        execution.result = {**(execution.result or {}), **evidence}
        execution.status = "succeeded" if evidence["passed"] else "failed"
        execution.finished_at = datetime.now(UTC)
        return ExecutionView.model_validate(execution)


@payment_chaos_router.get("/runs/{execution_id}")
def get_case(
    project_id: UUID,
    execution_id: UUID,
    session: DatabaseSession,
) -> ExecutionView:
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
