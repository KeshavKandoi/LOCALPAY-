from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import DatabaseSession, require_admin
from app.api.projects import get_project
from app.core.settings import Settings
from app.models import (
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.webhooks import fetch_endpoint_secret, protect_secret, signed_headers

webhook_router = APIRouter(
    prefix="/localpay/admin/v1/projects/{project_id}",
    tags=["LocalPay webhooks"],
    dependencies=[Depends(require_admin)],
)
EventType = Literal[
    "payment.authorized",
    "payment.captured",
    "payment.failed",
    "refund.created",
    "refund.processed",
    "refund.failed",
]


class EndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    secret: SecretStr = Field(min_length=16, max_length=128)
    enabled_events: set[EventType] = Field(min_length=1)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def validate_endpoint_url(cls, url: HttpUrl) -> HttpUrl:
        if (
            url.username is not None
            or url.password is not None
            or url.fragment is not None
        ):
            raise ValueError("Invalid webhook URL length, credentials, or fragment")
        return url


class EndpointView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    enabled_events: list[str]
    enabled: bool
    created_at: datetime


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    created_at: datetime


@webhook_router.post("/webhook-endpoints", status_code=201)
def add_endpoint(
    project_id: UUID,
    body: EndpointCreate,
    request: Request,
    session: DatabaseSession,
) -> EndpointView:
    settings: Settings = request.app.state.settings
    encryption_key = settings.webhook_encryption_key
    if encryption_key is None:
        raise HTTPException(503)
    try:
        with session.begin():
            get_project(session, project_id)
            endpoint = WebhookEndpoint(
                project_id=project_id,
                url=str(body.url),
                enabled_events=sorted(body.enabled_events),
                enabled=body.enabled,
                secret_ciphertext=protect_secret(encryption_key, body.secret),
            )
            session.add(endpoint)
            session.flush()
            result = EndpointView.model_validate(endpoint)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(409) from None
        raise
    return result


@webhook_router.get("/webhook-endpoints")
def get_endpoints(project_id: UUID, session: DatabaseSession) -> list[EndpointView]:
    get_project(session, project_id)
    rows = session.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.project_id == project_id)
        .order_by(WebhookEndpoint.created_at, WebhookEndpoint.id)
    )
    return [EndpointView.model_validate(row) for row in rows]


@webhook_router.get("/webhook-events")
def get_events(
    project_id: UUID,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[EventView]:
    get_project(session, project_id)
    events: Sequence[WebhookEvent] = session.scalars(
        select(WebhookEvent)
        .where(WebhookEvent.project_id == project_id)
        .order_by(WebhookEvent.created_at.desc(), WebhookEvent.id.desc())
        .limit(count)
    ).all()
    return [EventView.model_validate(event) for event in events]


@webhook_router.get("/webhook-events/{event_id}/payload")
def get_payload(project_id: UUID, event_id: UUID, session: DatabaseSession) -> Response:
    event = session.get(WebhookEvent, (project_id, event_id))
    if event is None:
        raise HTTPException(404)
    return Response(event.payload, media_type="application/json")


@webhook_router.get("/webhook-events/{event_id}/signed/{endpoint_id}")
def get_signed_payload(
    project_id: UUID,
    event_id: UUID,
    endpoint_id: UUID,
    request: Request,
    session: DatabaseSession,
) -> Response:
    event = session.get(WebhookEvent, (project_id, event_id))
    if event is None:
        raise HTTPException(404)
    ciphertext = fetch_endpoint_secret(
        session, project_id, endpoint_id, event.event_type
    )
    if ciphertext is None:
        raise HTTPException(404)
    settings: Settings = request.app.state.settings
    encryption_key = settings.webhook_encryption_key
    if encryption_key is None:
        raise HTTPException(503)
    headers = signed_headers(event, ciphertext, encryption_key)
    headers["Cache-Control"] = "no-store"
    return Response(event.payload, media_type="application/json", headers=headers)


class DeliveryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    endpoint_id: UUID
    status: str
    attempt_count: int
    next_retry_at: datetime


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_number: int
    http_status: int | None
    duration_ms: int | None
    error_code: str | None
    created_at: datetime


@webhook_router.get("/webhook-deliveries")
def get_deliveries(
    project_id: UUID,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DeliveryView]:
    get_project(session, project_id)
    rows = session.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.project_id == project_id)
        .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
        .limit(count)
    )
    return [DeliveryView.model_validate(row) for row in rows]


@webhook_router.get("/webhook-deliveries/{delivery_id}/attempts")
def get_attempts(
    project_id: UUID, delivery_id: UUID, session: DatabaseSession
) -> list[AttemptView]:
    delivery = session.get(WebhookDelivery, (project_id, delivery_id))
    if delivery is None:
        raise HTTPException(404)
    rows = session.scalars(
        select(WebhookDeliveryAttempt)
        .where(
            WebhookDeliveryAttempt.project_id == project_id,
            WebhookDeliveryAttempt.event_id == delivery.event_id,
            WebhookDeliveryAttempt.endpoint_id == delivery.endpoint_id,
        )
        .order_by(WebhookDeliveryAttempt.attempt_number)
    )
    return [AttemptView.model_validate(row) for row in rows]
