import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Payment, Refund, WebhookEvent
from app.services.payments import fetch_payment, transition

RefundOutcome = Literal["pending", "processed", "failed"]


class RefundError(Exception):
    def __init__(self, description: str, status: int = 400) -> None:
        self.description = description
        self.status = status


@dataclass(frozen=True, slots=True)
class RefundDetails:
    amount: int | None
    receipt: str | None
    notes: dict[str, str]
    reason: str | None = None
    outcome: RefundOutcome = "processed"

    def fingerprint(self, payment_id: str) -> str:
        payload = (
            payment_id,
            self.amount,
            self.receipt,
            self.notes,
            self.reason,
            self.outcome,
        )
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def refund_entity(refund: Refund, payment_id: str) -> dict[str, object]:
    return {
        "id": refund.public_id,
        "entity": "refund",
        "payment_id": payment_id,
        "amount": refund.amount,
        "currency": refund.currency,
        "status": refund.status,
        "receipt": refund.receipt,
        "notes": refund.notes or [],
        "speed_requested": "normal",
        "speed_processed": "normal" if refund.status == "processed" else None,
        "created_at": int(refund.created_at.timestamp()),
    }


def add_refund_event(
    session: Session, payment: Payment, refund: Refund, event_type: str
) -> None:
    event = {
        "entity": "event",
        "event": event_type,
        "contains": ["refund"],
        "payload": {"refund": {"entity": refund_entity(refund, payment.public_id)}},
        "created_at": int(refund.updated_at.timestamp()),
    }
    session.add(
        WebhookEvent(
            project_id=refund.project_id,
            event_type=event_type,
            payload=json.dumps(
                event, separators=(",", ":"), ensure_ascii=False
            ).encode(),
        )
    )


def create_refund(
    session: Session,
    project_id: UUID,
    payment_id: str,
    details: RefundDetails,
    key: str | None,
) -> tuple[Refund, Payment]:
    payment = fetch_payment(session, project_id, payment_id, lock=True)
    if payment is None:
        raise RefundError("The id provided does not exist", 404)
    fingerprint = details.fingerprint(payment_id)
    if key is not None:
        existing = session.scalar(
            select(Refund).where(
                Refund.project_id == project_id, Refund.idempotency_key == key
            )
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise RefundError(
                    "Different request with the same idempotency key has already been processed.",
                    409,
                )
            return existing, payment
    if payment.status == "refunded":
        raise RefundError("The payment has been fully refunded already.")
    if payment.status != "captured":
        raise RefundError("Only captured payments can be refunded.")
    reserved = session.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.project_id == project_id,
            Refund.payment_id == payment.id,
            Refund.status == "pending",
        )
    )
    available = payment.amount_captured - payment.amount_refunded - int(reserved or 0)
    amount = available if details.amount is None else details.amount
    if amount <= 0 or amount > available:
        raise RefundError(
            "The refund amount provided is greater than the refundable balance."
        )
    refund = Refund(
        project_id=project_id,
        payment_id=payment.id,
        amount=amount,
        currency=payment.currency,
        receipt=details.receipt,
        notes=details.notes,
        reason=details.reason,
        status="pending",
        idempotency_key=key,
        request_fingerprint=fingerprint if key is not None else None,
    )
    session.add(refund)
    session.flush()
    add_refund_event(session, payment, refund, "refund.created")
    if details.outcome != "pending":
        settle_refund(session, payment, refund, details.outcome)
    return refund, payment


def settle_refund(
    session: Session,
    payment: Payment,
    refund: Refund,
    outcome: Literal["processed", "failed"],
) -> None:
    if refund.status != "pending":
        raise RefundError("Only pending refunds can be resolved.", 409)
    refund.status = outcome
    if outcome == "processed":
        payment.amount_refunded += refund.amount
        if payment.amount_refunded == payment.amount_captured:
            transition(payment, "refunded")
    session.flush()
    add_refund_event(session, payment, refund, f"refund.{outcome}")


def fetch_refund(
    session: Session, project_id: UUID, public_id: str
) -> tuple[Refund, Payment] | None:
    row = session.execute(
        select(Refund, Payment)
        .join(
            Payment,
            (Payment.project_id == Refund.project_id)
            & (Payment.id == Refund.payment_id),
        )
        .where(Refund.project_id == project_id, Refund.public_id == public_id)
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


def list_refunds(
    session: Session, project_id: UUID, payment_id: str, count: int, skip: int
) -> list[Refund]:
    payment = fetch_payment(session, project_id, payment_id)
    if payment is None:
        raise RefundError("The id provided does not exist", 404)
    return list(
        session.scalars(
            select(Refund)
            .where(Refund.project_id == project_id, Refund.payment_id == payment.id)
            .order_by(Refund.created_at.desc(), Refund.id.desc())
            .offset(skip)
            .limit(count)
        )
    )


def resolve_refund(
    session: Session,
    project_id: UUID,
    public_id: str,
    outcome: Literal["processed", "failed"],
) -> tuple[Refund, Payment]:
    pair = fetch_refund(session, project_id, public_id)
    if pair is None:
        raise RefundError("The id provided does not exist", 404)
    refund, payment = pair
    session.refresh(payment, with_for_update=True)
    session.refresh(refund)
    settle_refund(session, payment, refund, outcome)
    return refund, payment
