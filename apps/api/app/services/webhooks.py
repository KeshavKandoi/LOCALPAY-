import json
from datetime import datetime
from hmac import compare_digest, digest
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WebhookDelivery, WebhookEndpoint, WebhookEvent

EVENT_TYPES = frozenset(
    {
        "payment.authorized",
        "payment.captured",
        "payment.failed",
        "refund.created",
        "refund.processed",
        "refund.failed",
    }
)
SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "X-Razorpay-Event-Id"


def sign_payload(payload: bytes, secret: bytes) -> str:
    return digest(secret, payload, "sha256").hex()


def verify_signature(payload: bytes, secret: bytes, signature: str) -> bool:
    return signature.isascii() and compare_digest(
        sign_payload(payload, secret), signature
    )


def record_event(
    session: Session,
    project_id: UUID,
    event_type: str,
    occurred_at: datetime,
    entities: dict[str, dict[str, object]],
) -> WebhookEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported webhook event type: {event_type}")
    body = {
        "entity": "event",
        "account_id": f"acc_{project_id.hex[:14]}",
        "event": event_type,
        "contains": list(entities),
        "payload": {name: {"entity": entity} for name, entity in entities.items()},
        "created_at": int(occurred_at.timestamp()),
    }
    event = WebhookEvent(
        project_id=project_id,
        event_type=event_type,
        created_at=occurred_at,
        payload=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode(),
    )
    session.add(event)
    session.flush()
    endpoints = session.scalars(
        select(WebhookEndpoint.id).where(
            WebhookEndpoint.project_id == project_id,
            WebhookEndpoint.enabled.is_(True),
            WebhookEndpoint.secret_ciphertext.is_not(None),
            WebhookEndpoint.enabled_events.contains([event_type]),
        )
    )
    session.add_all(
        WebhookDelivery(
            project_id=project_id, event_id=event.id, endpoint_id=endpoint_id
        )
        for endpoint_id in endpoints
    )
    return event


def protect_secret(encryption_key: SecretStr, secret: SecretStr) -> bytes:
    return Fernet(encryption_key.get_secret_value().encode()).encrypt(
        secret.get_secret_value().encode()
    )


def signed_headers(
    event: WebhookEvent, ciphertext: bytes, encryption_key: SecretStr
) -> dict[str, str]:
    secret = Fernet(encryption_key.get_secret_value().encode()).decrypt(ciphertext)
    return {
        SIGNATURE_HEADER: sign_payload(event.payload, secret),
        EVENT_ID_HEADER: f"evt_{event.id.hex}",
    }


def fetch_endpoint_secret(
    session: Session, project_id: UUID, endpoint_id: UUID, event_type: str
) -> bytes | None:
    return session.scalar(
        select(WebhookEndpoint.secret_ciphertext).where(
            WebhookEndpoint.project_id == project_id,
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.enabled.is_(True),
            WebhookEndpoint.enabled_events.contains([event_type]),
        )
    )
