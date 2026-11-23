from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select

from app.api.auth import DatabaseSession, require_admin
from app.api.projects import ProjectView
from app.models import (
    Order,
    Payment,
    Project,
    Refund,
    ReliabilityTestRun,
    SimulationScenario,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.reports import payment_timeline
from app.services.webhook_chaos import WebhookChaos, enqueue_chaos

projects_router = APIRouter(
    prefix="/localpay/admin/v1",
    tags=["LocalPay dashboard"],
    dependencies=[Depends(require_admin)],
)
dashboard_router = APIRouter(
    prefix="/localpay/admin/v1/projects/{project_id}/dashboard",
    tags=["LocalPay dashboard"],
    dependencies=[Depends(require_admin)],
)
Resource = Literal["orders", "payments", "refunds"]
RESOURCE_MODELS: dict[Resource, type[Order] | type[Payment] | type[Refund]] = {
    "orders": Order,
    "payments": Payment,
    "refunds": Refund,
}


@projects_router.get("/projects")
def projects(session: DatabaseSession) -> list[ProjectView]:
    return [
        ProjectView.model_validate(row)
        for row in session.scalars(
            select(Project).order_by(Project.name, Project.id)
        ).all()
    ]


@dashboard_router.get("/overview")
def overview(project_id: UUID, session: DatabaseSession) -> dict[str, object]:
    counts = {
        row[0]: row[1]
        for row in session.execute(
            select(Payment.status, func.count())
            .where(Payment.project_id == project_id)
            .group_by(Payment.status)
        )
    }
    deliveries = {
        row[0]: row[1]
        for row in session.execute(
            select(WebhookDelivery.status, func.count())
            .where(WebhookDelivery.project_id == project_id)
            .group_by(WebhookDelivery.status)
        )
    }
    volumes = session.execute(
        select(
            Payment.currency,
            func.sum(Payment.amount_captured),
        )
        .where(
            Payment.project_id == project_id,
            Payment.amount_captured > 0,
        )
        .group_by(Payment.currency)
        .order_by(Payment.currency)
    ).all()
    cutoff = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=13)
    day = func.date_trunc("day", Payment.created_at, "UTC")
    activity = {
        value.date().isoformat(): count
        for value, count in session.execute(
            select(day, func.count())
            .where(Payment.project_id == project_id, Payment.created_at >= cutoff)
            .group_by(day)
        )
    }
    activity_days = [
        (cutoff + timedelta(days=index)).date().isoformat() for index in range(14)
    ]
    recent = session.scalars(
        select(Payment)
        .where(
            Payment.project_id == project_id,
            Payment.status == "failed",
        )
        .order_by(Payment.created_at.desc())
        .limit(5)
    ).all()
    runs = session.scalars(
        select(ReliabilityTestRun)
        .where(
            ReliabilityTestRun.project_id == project_id,
        )
        .order_by(ReliabilityTestRun.created_at.desc())
        .limit(5)
    ).all()
    return {
        "payments": sum(counts.values()),
        "failed": counts.get("failed", 0),
        "captured": counts.get("captured", 0) + counts.get("refunded", 0),
        "deliveries": sum(deliveries.values()),
        "delivered": deliveries.get("delivered", 0),
        "volume": [
            {"currency": currency, "amount": str(amount)}
            for currency, amount in volumes
        ],
        "activity": [
            {"date": key, "count": activity.get(key, 0)} for key in activity_days
        ],
        "recent_failures": [
            {"id": row.public_id, "reason": row.error_description} for row in recent
        ],
        "recent_runs": [
            {"id": str(row.id), "name": row.suite_name, "status": row.status}
            for row in runs
        ],
    }


@dashboard_router.get("/records/{resource}")
def records(
    project_id: UUID,
    resource: Resource,
    session: DatabaseSession,
    search: Annotated[str, Query(max_length=120)] = "",
    status: Annotated[str, Query(max_length=20)] = "",
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> list[dict[str, object]]:
    model = RESOURCE_MODELS[resource]
    query = cast("Select[tuple[Order | Payment | Refund]]", select(model)).where(
        model.project_id == project_id
    )
    if search:
        condition = model.public_id.contains(search, autoescape=True)
        if model is Order or model is Refund:
            condition = or_(condition, model.receipt.contains(search, autoescape=True))
        query = query.where(condition)
    if status:
        query = query.where(model.status == status)
    return [
        {
            "id": row.public_id,
            "amount": str(row.amount),
            "currency": row.currency,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "reference": row.method if isinstance(row, Payment) else row.receipt,
        }
        for row in session.scalars(
            query.order_by(model.created_at.desc(), model.id.desc())
            .offset(offset)
            .limit(25)
        )
    ]


@dashboard_router.get("/records/{resource}/{public_id}")
def detail(
    project_id: UUID,
    resource: Resource,
    public_id: str,
    session: DatabaseSession,
) -> dict[str, object]:
    model = RESOURCE_MODELS[resource]
    query = cast("Select[tuple[Order | Payment | Refund]]", select(model))
    row = session.scalar(
        query.where(model.project_id == project_id, model.public_id == public_id)
    )
    if row is None:
        raise HTTPException(404)
    result: dict[str, object] = {
        "id": row.public_id,
        "amount": str(row.amount),
        "currency": row.currency,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }
    if isinstance(row, Order):
        payments = session.scalars(
            select(Payment.public_id)
            .where(
                Payment.project_id == project_id,
                Payment.order_id == row.id,
            )
            .order_by(Payment.created_at)
        ).all()
        result.update(
            amount_paid=str(row.amount_paid),
            amount_due=str(row.amount_due),
            receipt=row.receipt,
            notes=row.notes,
            payment_ids=list(payments),
        )
    elif isinstance(row, Payment):
        order_id = session.scalar(
            select(Order.public_id).where(
                Order.project_id == project_id,
                Order.id == row.order_id,
            )
        )
        result.update(
            order_id=order_id,
            method=row.method,
            error=row.error_description,
            amount_captured=str(row.amount_captured),
            amount_refunded=str(row.amount_refunded),
            timeline=[
                event
                for event in payment_timeline(session, project_id, order_id)
                if event["entity_id"] == row.public_id
            ],
        )
    else:
        payment_id = session.scalar(
            select(Payment.public_id).where(
                Payment.project_id == project_id,
                Payment.id == row.payment_id,
            )
        )
        result.update(
            payment_id=payment_id,
            reason=row.reason,
            receipt=row.receipt,
            notes=row.notes,
        )
    return result


class Replay(BaseModel):
    endpoint_id: UUID


@dashboard_router.post("/events/{event_id}/replay", status_code=202)
def replay(
    project_id: UUID, event_id: UUID, body: Replay, session: DatabaseSession
) -> dict[str, UUID]:
    with session.begin():
        endpoint = session.get(WebhookEndpoint, (project_id, body.endpoint_id))
        event = session.get(WebhookEvent, (project_id, event_id))
        if endpoint is None or not endpoint.enabled or event is None:
            raise HTTPException(404)
        scenario = SimulationScenario(
            project_id=project_id,
            name=f"replay-{uuid4().hex}",
            scenario_type="webhook.replay",
            configuration=WebhookChaos().model_dump(),
        )
        session.add(scenario)
        session.flush()
        try:
            run = enqueue_chaos(session, project_id, scenario, endpoint, [event])
        except ValueError as exc:
            raise HTTPException(422) from exc
        return {"execution_id": run.id}
