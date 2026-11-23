from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import DatabaseSession
from app.api.orders import GatewayProjectId, Note, ProjectId, Receipt
from app.api.razorpay import RazorpayError, RazorpayRoute
from app.services.refunds import (
    RefundDetails,
    RefundError,
    create_refund,
    fetch_refund,
    list_refunds,
    refund_entity,
    resolve_refund,
)

refund_router = APIRouter(prefix="/v1", tags=["Refunds"], route_class=RazorpayRoute)
refund_simulation_router = APIRouter(
    prefix="/localpay/v1/simulations", tags=["LocalPay simulation"]
)

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="X-Refund-Idempotency",
        min_length=10,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_-]+$",
    ),
]


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)] | None = (
        None
    )
    receipt: Receipt | None = None
    notes: Annotated[dict[Note, Note], Field(max_length=15)] = Field(
        default_factory=dict
    )
    speed: Literal["normal"] = "normal"


class RefundSimulationRequest(RefundRequest):
    reason: str | None = Field(default=None, max_length=255, pattern=r"^[^\x00]*$")
    outcome: Literal["pending", "processed", "failed"] = "pending"


class ResolveRefund(BaseModel):
    outcome: Literal["processed", "failed"]


def persist_refund(
    session: Session,
    project_id: UUID,
    payment_id: str,
    details: RefundDetails,
    key: str | None,
) -> dict[str, object]:
    try:
        refund, payment = create_refund(session, project_id, payment_id, details, key)
        result = refund_entity(refund, payment.public_id)
        session.commit()
    except RefundError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_refunds_project_id_idempotency_key":
            raise RefundError(
                "Different request with the same idempotency key has already been processed.",
                409,
            ) from None
        if constraint == "uq_refunds_project_id_payment_id_receipt":
            raise RefundError(
                "Duplicate request. This request has already been processed."
            ) from None
        raise
    return result


@refund_router.post("/payments/{payment_id}/refund")
def add_refund(
    payment_id: str,
    body: RefundRequest,
    project_id: GatewayProjectId,
    session: DatabaseSession,
    key: IdempotencyKey = None,
) -> dict[str, object]:
    try:
        return persist_refund(
            session,
            project_id,
            payment_id,
            RefundDetails(body.amount, body.receipt, body.notes),
            key,
        )
    except RefundError as exc:
        raise RazorpayError(
            exc.description, status=409 if exc.status == 409 else 400
        ) from None


@refund_router.get("/payments/{payment_id}/refunds")
def get_refunds(
    payment_id: str,
    project_id: GatewayProjectId,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 10,
    skip: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> dict[str, object]:
    try:
        items = [
            refund_entity(refund, payment_id)
            for refund in list_refunds(session, project_id, payment_id, count, skip)
        ]
    except RefundError as exc:
        raise RazorpayError(exc.description) from None
    return {"entity": "collection", "count": len(items), "items": items}


@refund_router.get("/refunds/{refund_id}")
@refund_router.get("/payments/{payment_id}/refunds/{refund_id}")
def get_refund(
    refund_id: str,
    project_id: GatewayProjectId,
    session: DatabaseSession,
    payment_id: str | None = None,
) -> dict[str, object]:
    pair = fetch_refund(session, project_id, refund_id)
    if pair is None or (payment_id is not None and pair[1].public_id != payment_id):
        raise RazorpayError("The id provided does not exist")
    return refund_entity(pair[0], pair[1].public_id)


@refund_simulation_router.post("/payments/{payment_id}/refunds", status_code=201)
def add_refund_simulation(
    payment_id: str,
    body: RefundSimulationRequest,
    project_id: ProjectId,
    session: DatabaseSession,
) -> dict[str, object]:
    try:
        return persist_refund(
            session,
            project_id,
            payment_id,
            RefundDetails(
                body.amount,
                body.receipt,
                body.notes,
                body.reason,
                body.outcome,
            ),
            None,
        )
    except RefundError as exc:
        raise HTTPException(exc.status) from None


@refund_simulation_router.post("/refunds/{refund_id}/resolve")
def settle_refund_simulation(
    refund_id: str,
    body: ResolveRefund,
    project_id: ProjectId,
    session: DatabaseSession,
) -> dict[str, object]:
    try:
        refund, payment = resolve_refund(session, project_id, refund_id, body.outcome)
        result = refund_entity(refund, payment.public_id)
        session.commit()
    except RefundError as exc:
        session.rollback()
        raise HTTPException(exc.status) from None
    return result
