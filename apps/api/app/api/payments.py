from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select

from app.api.auth import DatabaseSession
from app.api.orders import ProjectId
from app.api.razorpay import RazorpayError, RazorpayRoute
from app.models import Order, Payment
from app.services.payments import (
    Outcome,
    PaymentError,
    capture_payment,
    fetch_payment,
    simulate_payment,
)

simulation_router = APIRouter(
    prefix="/localpay/v1/simulations", tags=["LocalPay simulation"]
)
payments_router = APIRouter(
    prefix="/v1/payments", tags=["Payments"], route_class=RazorpayRoute
)


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^order_[a-zA-Z0-9]{14}$")
    scenario: Outcome = Outcome.SUCCESS
    method: Literal["card", "upi", "netbanking", "wallet", "emi", "paylater"] = "card"


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: StrictInt = Field(gt=0, le=9223372036854775807)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class PaymentView(BaseModel):
    id: str
    entity: Literal["payment"] = "payment"
    order_id: str
    amount: int
    currency: str
    status: str
    method: str | None
    amount_refunded: int
    refund_status: str | None
    captured: bool
    error_code: str | None
    error_description: str | None
    created_at: int

    @classmethod
    def from_payment(cls, payment: Payment, order_id: str) -> "PaymentView":
        refund_status = None
        if payment.amount_refunded:
            refund_status = (
                "full"
                if payment.amount_refunded == payment.amount_captured
                else "partial"
            )
        return cls(
            id=payment.public_id,
            order_id=order_id,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status,
            method=payment.method,
            amount_refunded=payment.amount_refunded,
            refund_status=refund_status,
            captured=payment.amount_captured > 0,
            error_code=payment.error_code,
            error_description=payment.error_description,
            created_at=int(payment.created_at.timestamp()),
        )


@simulation_router.post("/payments", status_code=201)
def add_simulation(
    body: SimulationRequest,
    response: Response,
    project_id: ProjectId,
    session: DatabaseSession,
) -> PaymentView:
    try:
        payment = simulate_payment(
            session, project_id, body.order_id, body.method, body.scenario
        )
        result = PaymentView.from_payment(payment, body.order_id)
        session.commit()
    except PaymentError as exc:
        session.rollback()
        raise HTTPException(
            404 if exc.description == "The id provided does not exist" else 409
        ) from None
    if body.scenario == Outcome.TIMEOUT:
        response.status_code = 504
    elif body.scenario == Outcome.NETWORK_INTERRUPTION:
        response.status_code = 503
    return result


@payments_router.get("/{payment_id}")
def get_payment(
    payment_id: str, project_id: ProjectId, session: DatabaseSession
) -> PaymentView:
    payment = fetch_payment(session, project_id, payment_id)
    if payment is None:
        raise RazorpayError("The id provided does not exist")
    order_id = session.scalar(
        select(Order.public_id).where(
            Order.project_id == project_id, Order.id == payment.order_id
        )
    )
    if order_id is None:
        raise RuntimeError("Payment has no order")
    return PaymentView.from_payment(payment, order_id)


@payments_router.post("/{payment_id}/capture")
def capture(
    payment_id: str,
    body: CaptureRequest,
    project_id: ProjectId,
    session: DatabaseSession,
) -> PaymentView:
    try:
        payment, order = capture_payment(
            session, project_id, payment_id, body.amount, body.currency
        )
        result = PaymentView.from_payment(payment, order.public_id)
        session.commit()
    except PaymentError as exc:
        session.rollback()
        raise RazorpayError(exc.description, exc.field) from None
    return result
