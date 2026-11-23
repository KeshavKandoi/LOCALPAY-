from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import IntegrityError

from app.api.auth import DatabaseSession, require_project
from app.api.razorpay import RazorpayError, RazorpayRoute
from app.models import Order
from app.services.orders import OrderFilters, create_order, fetch_order, list_orders
from app.services.payment_chaos import consume_gateway_fault

orders_router = APIRouter(
    prefix="/v1/orders", tags=["Orders"], route_class=RazorpayRoute
)
ProjectId = Annotated[UUID, Depends(require_project)]


def require_gateway_project(project_id: ProjectId, session: DatabaseSession) -> UUID:
    code = consume_gateway_fault(session, project_id)
    session.commit()
    if code is not None:
        description = (
            "Simulated rate limit."
            if code == 429
            else "Simulated gateway unavailability."
        )
        raise RazorpayError(description, status=code)
    return project_id


GatewayProjectId = Annotated[UUID, Depends(require_gateway_project)]
Receipt = Annotated[str, StringConstraints(max_length=40, pattern=r"^[^\x00]*$")]
Note = Annotated[str, StringConstraints(max_length=256, pattern=r"^[^\x00]*$")]
CURRENCIES = frozenset(
    "AED ALL AMD ARS AUD AWG BBD BDT BHD BMD BND BOB BSD BWP BZD CAD CHF CNY COP CRC "
    "CZK DKK DOP DZD EGP ETB EUR FJD GBP GHS GIP GMD GTQ GYD HKD HNL HRK HTG HUF IDR "
    "ILS INR JMD JPY KES KGS KHR KWD KYD KZT LAK LBP LKR LRD LSL MAD MDL MKD MMK MNT "
    "MOP MUR MVR MWK MXN MYR NAD NGN NIO NOK NPR NZD OMR PEN PGK PHP PKR QAR SAR SCR "
    "SEK SGD SLL SOS SSP SVC SZL THB TTD TZS USD UYU UZS YER ZAR".split()
)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
    currency: Annotated[str, StringConstraints(min_length=3, max_length=3)]
    receipt: Receipt | None = None
    notes: Annotated[dict[Note, Note], Field(max_length=15)] = Field(
        default_factory=dict
    )


class OrderView(BaseModel):
    id: str
    entity: Literal["order"] = "order"
    amount: int
    amount_paid: int
    amount_due: int
    currency: str
    receipt: str | None
    offer_id: None = None
    status: str
    attempts: int
    notes: dict[str, str] | list[str]
    created_at: int

    @classmethod
    def from_order(cls, order: Order) -> "OrderView":
        return cls(
            id=order.public_id,
            amount=order.amount,
            amount_paid=order.amount_paid,
            amount_due=order.amount_due,
            currency=order.currency,
            receipt=order.receipt,
            status=order.status,
            attempts=order.attempts,
            notes=order.notes or [],
            created_at=int(order.created_at.timestamp()),
        )


class OrderCollection(BaseModel):
    entity: Literal["collection"] = "collection"
    count: int
    items: list[OrderView]


@orders_router.post("")
def add_order(
    body: OrderCreate, project_id: GatewayProjectId, session: DatabaseSession
) -> OrderView:
    if body.currency not in CURRENCIES:
        raise RazorpayError(
            "currency: validation_failure: BAD_REQUEST_INVALID_CURRENCY.", "currency"
        )
    if body.currency == "INR" and body.amount < 100:
        raise RazorpayError("The amount must be at least INR 1.00", "amount")
    if body.amount == 0 or (
        body.currency in {"BHD", "KWD", "OMR"} and body.amount % 10
    ):
        raise RazorpayError("Invalid amount for currency.", "amount")
    try:
        order = create_order(
            session,
            project_id,
            amount=body.amount,
            currency=body.currency,
            receipt=body.receipt,
            notes=body.notes,
        )
        result = OrderView.from_order(order)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == "uq_orders_project_id_receipt"
        ):
            raise RazorpayError(
                "Duplicate request. This request has already been processed.", "receipt"
            ) from None
        raise
    return result


@orders_router.get("/{order_id}")
def get_order(
    order_id: str, project_id: GatewayProjectId, session: DatabaseSession
) -> OrderView:
    order = fetch_order(session, project_id, order_id)
    if order is None:
        raise RazorpayError("The id provided does not exist")
    return OrderView.from_order(order)


@orders_router.get("")
def get_orders(
    project_id: GatewayProjectId,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 10,
    skip: Annotated[int, Query(ge=0, le=2147483647)] = 0,
    receipt: Annotated[Receipt | None, Query()] = None,
    from_epoch: Annotated[
        int | None, Query(alias="from", ge=0, le=253402300798)
    ] = None,
    to_epoch: Annotated[int | None, Query(alias="to", ge=0, le=253402300798)] = None,
    authorized: Annotated[int | None, Query(ge=0, le=1)] = None,
) -> OrderCollection:
    if from_epoch is not None and to_epoch is not None and from_epoch > to_epoch:
        raise RazorpayError("Invalid timestamp range.", "from")
    items = [
        OrderView.from_order(order)
        for order in list_orders(
            session,
            project_id,
            OrderFilters(count, skip, receipt, from_epoch, to_epoch, authorized),
        )
    ]
    return OrderCollection(count=len(items), items=items)
