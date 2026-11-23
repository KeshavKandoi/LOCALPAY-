from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address, ip_network
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import (
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.webhooks import signed_headers

LOCAL_NETWORKS = tuple(
    ip_network(block)
    for block in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)
LEASE_SECONDS = 30


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    project_id: UUID
    delivery_id: UUID
    token: UUID
    attempt: int
    url: str
    payload: bytes
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    http_status: int | None = None
    error_code: str | None = None
    retryable: bool = False

    @property
    def delivered(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 300


def pin_destination(url: str, targets: dict[str, str]) -> tuple[httpx.URL, str]:
    parsed = httpx.URL(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.userinfo
        or parsed.fragment
    ):
        raise ValueError("Invalid webhook target")
    origin = str(parsed.copy_with(path="/", query=None, fragment=None)).removesuffix(
        "/"
    )
    address = targets.get(origin)
    if address is None:
        raise ValueError("Webhook target is not allowlisted")
    ip = ip_address(address)
    if not any(ip in network for network in LOCAL_NETWORKS):
        raise ValueError("Webhook target is not a local address")
    host = origin.split("://", 1)[1]
    return parsed.copy_with(host=str(ip)), host


def send(claim: DeliveryClaim, settings: Settings) -> DeliveryResult:
    try:
        target, host = pin_destination(claim.url, settings.webhook_targets)
    except (ValueError, httpx.InvalidURL):
        return DeliveryResult(error_code="unsafe_destination")
    hostname = httpx.URL(claim.url).host
    try:
        with (
            httpx.Client(
                timeout=settings.webhook_timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream(
                "POST",
                target,
                content=claim.payload,
                headers={
                    **claim.headers,
                    "Host": host,
                    "Content-Type": "application/json",
                },
                extensions={"sni_hostname": hostname},
            ) as response,
        ):
            status = response.status_code
            return DeliveryResult(
                http_status=status, retryable=status in {408, 429} or status >= 500
            )
    except httpx.TimeoutException:
        return DeliveryResult(error_code="timeout", retryable=True)
    except httpx.TransportError:
        return DeliveryResult(error_code="connection_error", retryable=True)


def due_deliveries(session: Session, now: datetime) -> list[tuple[UUID, UUID]]:
    rows = session.execute(
        select(WebhookDelivery.project_id, WebhookDelivery.id)
        .where(
            or_(
                and_(
                    WebhookDelivery.status.in_(("pending", "retry")),
                    WebhookDelivery.next_retry_at <= now,
                ),
                and_(
                    WebhookDelivery.status == "processing",
                    WebhookDelivery.leased_until <= now,
                ),
            )
        )
        .order_by(WebhookDelivery.next_retry_at)
        .limit(100)
    )
    return [(row[0], row[1]) for row in rows]


def attempt_record(
    row: WebhookDelivery, result: DeliveryResult, duration_ms: int
) -> WebhookDeliveryAttempt:
    return WebhookDeliveryAttempt(
        project_id=row.project_id,
        event_id=row.event_id,
        endpoint_id=row.endpoint_id,
        attempt_number=row.attempt_count,
        http_status=result.http_status,
        duration_ms=duration_ms,
        error_code=result.error_code,
    )


def claim_delivery(
    session: Session,
    project_id: UUID,
    delivery_id: UUID,
    now: datetime,
    settings: Settings,
) -> DeliveryClaim | None:
    row = session.get(WebhookDelivery, (project_id, delivery_id), with_for_update=True)
    if row is None or row.status in {"delivered", "failed"}:
        return None
    if row.status == "processing":
        if row.leased_until is None or row.leased_until > now:
            return None
        session.add(attempt_record(row, DeliveryResult(error_code="lease_expired"), 0))
    elif row.next_retry_at > now:
        return None
    if row.attempt_count >= settings.webhook_max_attempts:
        row.status = "failed"
        row.lease_token = None
        row.leased_until = None
        return None
    row.attempt_count += 1
    endpoint = session.get(WebhookEndpoint, (project_id, row.endpoint_id))
    event = session.get(WebhookEvent, (project_id, row.event_id))
    ciphertext = session.scalar(
        select(WebhookEndpoint.secret_ciphertext).where(
            WebhookEndpoint.project_id == project_id,
            WebhookEndpoint.id == row.endpoint_id,
        )
    )
    key = settings.webhook_encryption_key
    if (
        endpoint is None
        or not endpoint.enabled
        or event is None
        or key is None
        or ciphertext is None
    ):
        fail_claim(session, row, "endpoint_unavailable")
        return None
    try:
        headers = signed_headers(event, ciphertext, key)
    except InvalidToken:
        fail_claim(session, row, "secret_unavailable")
        return None
    token = uuid4()
    row.status = "processing"
    row.lease_token = token
    row.leased_until = now + timedelta(seconds=LEASE_SECONDS)
    return DeliveryClaim(
        project_id,
        delivery_id,
        token,
        row.attempt_count,
        endpoint.url,
        event.payload,
        headers,
    )


def fail_claim(session: Session, row: WebhookDelivery, reason: str) -> None:
    row.status = "failed"
    row.lease_token = None
    row.leased_until = None
    session.add(attempt_record(row, DeliveryResult(error_code=reason), 0))


def finish_delivery(
    session: Session,
    claim: DeliveryClaim,
    result: DeliveryResult,
    now: datetime,
    duration_ms: int,
    settings: Settings,
) -> bool:
    row = session.get(
        WebhookDelivery, (claim.project_id, claim.delivery_id), with_for_update=True
    )
    if row is None or row.status != "processing" or row.lease_token != claim.token:
        return False
    session.add(attempt_record(row, result, duration_ms))
    row.lease_token = None
    row.leased_until = None
    if result.delivered:
        row.status = "delivered"
    elif result.retryable and row.attempt_count < settings.webhook_max_attempts:
        row.status = "retry"
        delay = min(900, settings.webhook_retry_seconds * 2 ** (row.attempt_count - 1))
        row.next_retry_at = now + timedelta(seconds=delay)
    else:
        row.status = "failed"
    return True


def scan(engine: Engine) -> list[tuple[UUID, UUID]]:
    with Session(engine) as session:
        return due_deliveries(session, datetime.now(UTC))
