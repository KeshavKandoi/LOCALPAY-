from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Order, Payment


@dataclass(frozen=True, slots=True)
class OrderFilters:
    count: int
    skip: int
    receipt: str | None
    from_epoch: int | None
    to_epoch: int | None
    authorized: int | None


def create_order(
    session: Session,
    project_id: UUID,
    *,
    amount: int,
    currency: str,
    receipt: str | None,
    notes: dict[str, str],
) -> Order:
    order = Order(
        project_id=project_id,
        amount=amount,
        currency=currency,
        receipt=receipt,
        notes=notes,
    )
    session.add(order)
    session.flush()
    return order


def fetch_order(session: Session, project_id: UUID, public_id: str) -> Order | None:
    return session.scalar(
        select(Order).where(
            Order.project_id == project_id, Order.public_id == public_id
        )
    )


def list_orders(
    session: Session, project_id: UUID, filters: OrderFilters
) -> list[Order]:
    query = select(Order).where(Order.project_id == project_id)
    if filters.receipt is not None:
        query = query.where(Order.receipt.contains(filters.receipt, autoescape=True))
    if filters.from_epoch is not None:
        query = query.where(
            Order.created_at >= datetime.fromtimestamp(filters.from_epoch, UTC)
        )
    if filters.to_epoch is not None:
        query = query.where(
            Order.created_at < datetime.fromtimestamp(filters.to_epoch + 1, UTC)
        )
    if filters.authorized is not None:
        authorized = exists().where(
            Payment.project_id == Order.project_id,
            Payment.order_id == Order.id,
            Payment.amount_authorized > 0,
        )
        query = query.where(authorized if filters.authorized else ~authorized)
    return list(
        session.scalars(
            query.order_by(Order.created_at.desc(), Order.id.desc())
            .offset(filters.skip)
            .limit(filters.count)
        )
    )
