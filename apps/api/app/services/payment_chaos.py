from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Barrier
from time import monotonic, sleep
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    GatewayFault,
    JsonObject,
    Order,
    Payment,
    Project,
    Refund,
    ScenarioExecution,
    SimulationScenario,
)
from app.services.orders import create_order
from app.services.payments import (
    Outcome,
    PaymentError,
    capture_payment,
    payment_entity,
    simulate_payment,
    transition,
)
from app.services.refunds import RefundDetails, RefundError, create_refund
from app.services.webhooks import record_event


class PaymentChaosType(StrEnum):
    DUPLICATE_PAYMENT = "payment.duplicate"
    TIMEOUT_RETRY = "payment.timeout_retry"
    CONCURRENT_CAPTURE = "payment.concurrent_capture"
    DELAYED_AUTHORIZATION = "payment.delayed_authorization"
    OUTAGE = "payment.gateway_outage"
    FAILURE_RETRY = "payment.failure_retry"
    CONCURRENT_REFUNDS = "payment.concurrent_refunds"
    DUPLICATE_REFUND = "payment.duplicate_refund"
    RATE_LIMIT = "payment.rate_limit"
    API_UNAVAILABLE = "payment.api_unavailability"
    AMBIGUOUS_RESULT = "payment.ambiguous_result"
    INTERRUPTED_TRANSACTION = "payment.interrupted_transaction"


FAULT_CODES = {
    PaymentChaosType.OUTAGE: 503,
    PaymentChaosType.RATE_LIMIT: 429,
    PaymentChaosType.API_UNAVAILABLE: 503,
}


class ChaosConflict(Exception):
    pass


def create_execution(
    session: Session, project_id: UUID, kind: PaymentChaosType
) -> ScenarioExecution:
    if session.get(Project, project_id, with_for_update=True) is None:
        raise LookupError("Project not found")
    name = str(kind)
    scenario = session.scalar(
        select(SimulationScenario).where(
            SimulationScenario.project_id == project_id,
            SimulationScenario.name == name,
        )
    )
    if scenario is None:
        scenario = SimulationScenario(
            project_id=project_id,
            name=name,
            scenario_type=name,
            configuration={},
        )
        session.add(scenario)
        session.flush()
    if scenario.scenario_type != name or not scenario.enabled:
        raise ChaosConflict("Scenario is unavailable")
    execution = ScenarioExecution(
        project_id=project_id,
        scenario_id=scenario.id,
        status="running",
        result={"type": name},
    )
    session.add(execution)
    session.flush()
    return execution


def arm_gateway_fault(
    session: Session, execution: ScenarioExecution, status_code: int, requests: int
) -> None:
    prior = session.get(GatewayFault, execution.project_id, with_for_update=True)
    if prior is not None:
        if prior.expires_at > datetime.now(UTC) and prior.remaining > 0:
            raise ChaosConflict("An active gateway fault already exists")
        finalize_fault(session, prior, "failed")
    session.add(
        GatewayFault(
            project_id=execution.project_id,
            execution_id=execution.id,
            status_code=status_code,
            remaining=requests,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )
    )
    execution.result = {
        **(execution.result or {}),
        "responses": [],
        "expected_status": status_code,
    }


def finalize_fault(session: Session, fault: GatewayFault, status: str) -> None:
    execution = session.get(ScenarioExecution, (fault.project_id, fault.execution_id))
    if execution is None:
        raise RuntimeError("Gateway fault execution is missing")
    execution.status = status
    execution.finished_at = datetime.now(UTC)
    session.delete(fault)
    session.flush()


def consume_gateway_fault(session: Session, project_id: UUID) -> int | None:
    fault = session.get(GatewayFault, project_id, with_for_update=True)
    if fault is None:
        return None
    if fault.expires_at <= datetime.now(UTC):
        finalize_fault(session, fault, "failed")
        return None
    code = fault.status_code
    execution = session.get(ScenarioExecution, (project_id, fault.execution_id))
    if execution is None:
        raise RuntimeError("Gateway fault execution is missing")
    evidence = execution.result or {}
    execution.result = {**evidence, "responses": [*evidence.get("responses", []), code]}
    fault.remaining -= 1
    if fault.remaining == 0:
        finalize_fault(session, fault, "succeeded")
    return code


def cancel_gateway_fault(
    session: Session, project_id: UUID, execution_id: UUID
) -> bool:
    fault = session.get(GatewayFault, project_id, with_for_update=True)
    if fault is None or fault.execution_id != execution_id:
        return False
    finalize_fault(session, fault, "cancelled")
    return True


def concurrently(operation: Callable[[], bool]) -> int:
    barrier = Barrier(2, timeout=10)

    def operation_after_barrier(index: int) -> bool:
        barrier.wait()
        return operation()

    with ThreadPoolExecutor(max_workers=2) as executor:
        return sum(executor.map(operation_after_barrier, range(2)))


def execute_transaction_case(
    engine: Engine,
    project_id: UUID,
    execution_id: UUID,
    kind: PaymentChaosType,
    amount: int,
    delay_ms: int = 50,
) -> JsonObject:
    with Session(engine) as session, session.begin():
        order = create_order(
            session,
            project_id,
            amount=amount,
            currency="INR",
            receipt=f"chaos-{execution_id.hex}",
            notes={},
        )
        order_id = order.public_id
        order_pk = order.id

    def simulate(outcome: Outcome, key: str | None = None) -> tuple[str, str]:
        with Session(engine) as session, session.begin():
            payment = simulate_payment(
                session, project_id, order_id, "card", outcome, key
            )
            return payment.public_id, payment.status

    def capture_once(payment_id: str, *, interrupt: bool = False) -> bool:
        with Session(engine) as session, session.begin():
            try:
                with session.begin_nested():
                    capture_payment(session, project_id, payment_id, amount, "INR")
                    if interrupt:
                        raise InterruptedError("Requested interruption")
            except (PaymentError, InterruptedError):
                return False
            return True

    def refund_once(payment_id: str, key: str | None = None) -> str | None:
        with Session(engine) as session, session.begin():
            try:
                with session.begin_nested():
                    refund, _ = create_refund(
                        session,
                        project_id,
                        payment_id,
                        RefundDetails(amount, None, {}),
                        key,
                    )
                    return refund.public_id
            except RefundError:
                return None

    evidence: JsonObject = {"order_id": order_id, "initial_balance": amount}
    success = False
    if kind in {PaymentChaosType.DUPLICATE_PAYMENT, PaymentChaosType.AMBIGUOUS_RESULT}:
        key = execution_id.hex
        first = simulate(Outcome.SUCCESS, key)
        if kind == PaymentChaosType.AMBIGUOUS_RESULT:
            evidence["first_response"] = "simulated_timeout_after_commit"
        second = simulate(Outcome.SUCCESS, key)
        evidence.update(payment_ids=[first[0], second[0]], same_payment=first == second)
        success = first == second and capture_once(first[0])
    elif kind in {PaymentChaosType.TIMEOUT_RETRY, PaymentChaosType.FAILURE_RETRY}:
        outcome = (
            Outcome.TIMEOUT
            if kind == PaymentChaosType.TIMEOUT_RETRY
            else Outcome.FAILED
        )
        first = simulate(outcome)
        payment_id, _ = simulate(Outcome.SUCCESS)
        evidence.update(first_state=first[1], retry_payment_id=payment_id)
        success = not capture_once(first[0]) and capture_once(payment_id)
    elif kind == PaymentChaosType.DELAYED_AUTHORIZATION:
        payment_id, initial = simulate(Outcome.TIMEOUT)
        waiting_since = monotonic()
        sleep(delay_ms / 1000)
        with Session(engine) as session, session.begin():
            payment = session.scalar(
                select(Payment)
                .where(
                    Payment.project_id == project_id,
                    Payment.public_id == payment_id,
                )
                .with_for_update()
            )
            if payment is None:
                raise RuntimeError("Delayed payment is missing")
            transition(payment, "authorized")
            payment.amount_authorized = payment.amount
            session.flush()
            record_event(
                session,
                project_id,
                "payment.authorized",
                payment.updated_at,
                {
                    "payment": payment_entity(payment, order_id),
                },
            )
        evidence.update(
            initial_state=initial,
            resumed_state="authorized",
            elapsed_ms=int((monotonic() - waiting_since) * 1000),
        )
        success = initial == "created" and capture_once(payment_id)
    elif kind == PaymentChaosType.CONCURRENT_CAPTURE:
        payment_id, _ = simulate(Outcome.SUCCESS)
        winners = concurrently(lambda: capture_once(payment_id))
        evidence["accepted_captures"] = winners
        success = winners == 1
    elif kind in {
        PaymentChaosType.CONCURRENT_REFUNDS,
        PaymentChaosType.DUPLICATE_REFUND,
    }:
        payment_id, _ = simulate(Outcome.SUCCESS)
        if not capture_once(payment_id):
            raise RuntimeError("Refund scenario setup failed")
        if kind == PaymentChaosType.CONCURRENT_REFUNDS:
            winners = concurrently(lambda: refund_once(payment_id) is not None)
            evidence["accepted_refunds"] = winners
            success = winners == 1
        else:
            first_refund = refund_once(payment_id, execution_id.hex)
            repeated_refund = refund_once(payment_id, execution_id.hex)
            evidence.update(refund_ids=[first_refund, repeated_refund])
            success = first_refund is not None and first_refund == repeated_refund
    elif kind == PaymentChaosType.INTERRUPTED_TRANSACTION:
        payment_id, _ = simulate(Outcome.SUCCESS)
        interrupted = not capture_once(payment_id, interrupt=True)
        with Session(engine) as session:
            order_after_interruption = session.get(Order, (project_id, order_pk))
            committed_after_interruption = (
                order_after_interruption.amount_paid
                if order_after_interruption
                else None
            )
        evidence.update(
            interrupted=interrupted,
            amount_paid_after_interruption=committed_after_interruption,
        )
        success = (
            interrupted
            and committed_after_interruption == 0
            and capture_once(payment_id)
        )
    with Session(engine) as session:
        stored = session.get(Order, (project_id, order_pk))
        refund_total = session.scalar(
            select(func.coalesce(func.sum(Refund.amount), 0))
            .join(
                Payment,
                (Payment.project_id == Refund.project_id)
                & (Payment.id == Refund.payment_id),
            )
            .where(
                Payment.project_id == project_id,
                Payment.order_id == order_pk,
                Refund.status == "processed",
            )
        )
        if stored is None:
            raise RuntimeError("Scenario order is missing")
        evidence.update(
            amount_paid=stored.amount_paid, amount_refunded=int(refund_total or 0)
        )
        evidence["passed"] = (
            success
            and stored.amount_paid == amount
            and int(refund_total or 0) <= amount
        )
    return evidence
