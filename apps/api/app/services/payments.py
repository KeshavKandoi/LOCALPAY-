from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Payment
from app.services.webhooks import record_event


class Outcome(StrEnum):
    SUCCESS = "payment.success"
    FAILED = "payment.failed"
    INSUFFICIENT_FUNDS = "payment.insufficient_funds"
    AUTHORIZATION_FAILED = "payment.authorization_failed"
    CAPTURE_FAILED = "payment.capture_failed"
    TIMEOUT = "payment.timeout"
    NETWORK_INTERRUPTION = "payment.network_interruption"


FAILURE_DETAILS = {
    Outcome.FAILED: ("PAYMENT_ERROR", "Payment failed in the configured simulation."),
    Outcome.INSUFFICIENT_FUNDS: (
        "PAYMENT_ERROR",
        "Insufficient funds in the configured simulation.",
    ),
    Outcome.AUTHORIZATION_FAILED: (
        "PAYMENT_ERROR",
        "Authorization rejected in the configured simulation.",
    ),
}
TRANSITIONS = {
    "created": frozenset({"authorized", "failed"}),
    "authorized": frozenset({"captured"}),
    "captured": frozenset({"refunded"}),
    "failed": frozenset(),
    "refunded": frozenset(),
}


class PaymentError(Exception):
    def __init__(self, description: str, field: str | None = None) -> None:
        self.description = description
        self.field = field


def transition(payment: Payment, target: str) -> None:
    if target not in TRANSITIONS.get(payment.status, ()):
        raise PaymentError(
            f"Payment cannot transition from {payment.status} to {target}."
        )
    payment.status = target


def payment_entity(payment: Payment, order_id: str) -> dict[str, object]:
    refund_status = None
    if payment.amount_refunded:
        refund_status = (
            "full" if payment.amount_refunded == payment.amount_captured else "partial"
        )
    return {
        "id": payment.public_id,
        "entity": "payment",
        "order_id": order_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "method": payment.method,
        "status": payment.status,
        "captured": payment.amount_captured > 0,
        "amount_refunded": payment.amount_refunded,
        "refund_status": refund_status,
        "error_code": payment.error_code,
        "error_description": payment.error_description,
        "created_at": int(payment.created_at.timestamp()),
    }


def simulate_payment(
    session: Session,
    project_id: UUID,
    order_id: str,
    method: str,
    outcome: Outcome,
    simulation_key: str | None = None,
) -> Payment:
    order = session.scalar(
        select(Order)
        .where(Order.project_id == project_id, Order.public_id == order_id)
        .with_for_update()
    )
    if order is None:
        raise PaymentError("The id provided does not exist", "order_id")
    if simulation_key is not None:
        existing = session.scalar(
            select(Payment).where(
                Payment.project_id == project_id,
                Payment.simulation_key == simulation_key,
            )
        )
        if existing is not None:
            if (
                existing.order_id != order.id
                or existing.method != method
                or existing.simulation_outcome != outcome
            ):
                raise PaymentError(
                    "The simulation key was used for a different request."
                )
            return existing
    if order.status == "paid" or order.amount_due == 0:
        raise PaymentError("The order is already paid.", "order_id")
    payment = Payment(
        project_id=project_id,
        order_id=order.id,
        currency=order.currency,
        amount=order.amount_due,
        method=method,
        status="created",
        capture_failure=outcome == Outcome.CAPTURE_FAILED,
        simulation_key=simulation_key,
        simulation_outcome=outcome,
    )
    if outcome in FAILURE_DETAILS:
        transition(payment, "failed")
        payment.error_code, payment.error_description = FAILURE_DETAILS[outcome]
    elif outcome not in {Outcome.TIMEOUT, Outcome.NETWORK_INTERRUPTION}:
        transition(payment, "authorized")
        payment.amount_authorized = payment.amount
    order.attempts += 1
    order.status = "attempted"
    session.add(payment)
    session.flush()
    if payment.status in {"authorized", "failed"}:
        record_event(
            session,
            project_id,
            f"payment.{payment.status}",
            payment.created_at,
            {"payment": payment_entity(payment, order.public_id)},
        )
    return payment


def fetch_payment(
    session: Session, project_id: UUID, public_id: str, *, lock: bool = False
) -> Payment | None:
    query = select(Payment).where(
        Payment.project_id == project_id, Payment.public_id == public_id
    )
    return session.scalar(query.with_for_update() if lock else query)


def capture_payment(
    session: Session, project_id: UUID, public_id: str, amount: int, currency: str
) -> tuple[Payment, Order]:
    payment = fetch_payment(session, project_id, public_id, lock=True)
    if payment is None:
        raise PaymentError("The id provided does not exist")
    if payment.status != "authorized":
        raise PaymentError("Payment is not in the authorized state.")
    if payment.currency != currency:
        raise PaymentError("The currency must match the payment currency.", "currency")
    if amount != payment.amount_authorized:
        raise PaymentError(
            "The capture amount must equal the authorized amount.", "amount"
        )
    if payment.capture_failure:
        raise PaymentError("Capture failed in the configured simulation.")
    order = session.get(Order, (project_id, payment.order_id), with_for_update=True)
    if order is None or order.amount_due < amount:
        raise PaymentError("The order has insufficient outstanding balance.", "amount")
    transition(payment, "captured")
    payment.amount_captured = amount
    order.amount_paid += amount
    if order.amount_paid == order.amount:
        order.status = "paid"
    session.flush()
    record_event(
        session,
        project_id,
        "payment.captured",
        payment.updated_at,
        {"payment": payment_entity(payment, order.public_id)},
    )
    return payment, order
