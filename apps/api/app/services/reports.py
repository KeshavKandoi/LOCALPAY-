import json
import re
from collections import Counter
from html import escape
from statistics import median
from typing import Any
from uuid import UUID
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models import (
    JsonObject,
    Order,
    Payment,
    ReliabilityTestRun,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEvent,
)

CASE_STATES = ("passed", "failed", "error", "inconclusive")


def diagnostics(case: JsonObject) -> list[JsonObject]:
    result = []
    evidence = case.get("evidence") or {}
    configuration = evidence.get("webhook_configuration") or {}
    for assertion in case.get("assertions", []):
        if assertion.get("status") != "failed":
            continue
        observed = assertion.get("observed")
        expected = assertion.get("expected")
        if (
            assertion.get("type") == "application_event_count"
            and expected == 1
            and evidence.get("event_count") == 1
            and configuration.get("duplicate_count", 0) > 1
            and type(observed) is int
            and observed > 1
        ):
            result.append(
                {
                    "code": "duplicate_processing",
                    "classification": "confirmed",
                    "message": "The application reported processing the event more than once.",
                    "suggestion": "Deduplicate webhook processing by event ID before writing business state.",
                }
            )
        if (
            assertion.get("type") == "application_event_count"
            and expected == 0
            and type(observed) is int
            and observed > 0
        ):
            if (
                evidence.get("event_count") == 1
                and evidence.get("only_invalid_signatures_observed") is True
            ):
                result.append(
                    {
                        "code": "invalid_signature_processing",
                        "classification": "confirmed",
                        "message": "The application reported processing a delivery configured with an invalid signature.",
                        "suggestion": "Verify the signature against the raw request bytes before processing.",
                    }
                )
    if (
        type(evidence.get("amount_refunded")) is int
        and type(evidence.get("amount_paid")) is int
    ):
        if evidence["amount_refunded"] > evidence["amount_paid"]:
            result.append(
                {
                    "code": "refund_inconsistency",
                    "classification": "confirmed",
                    "message": "Recorded refunds exceed the captured total.",
                    "suggestion": "Reserve refundable amounts under the same payment transaction lock.",
                }
            )
    if evidence.get("waiting_timed_out"):
        result.append(
            {
                "code": "evidence_timeout",
                "classification": "suspected",
                "message": "The webhook scenario was still running when the observation window closed.",
                "suggestion": "Inspect the delivery timeline and rerun with a shorter delay or retry backoff.",
            }
        )
    return result


def evidence_uuid(value: Any) -> UUID | None:
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def payment_timeline(
    session: Session, project_id: UUID, order_public_id: Any
) -> list[JsonObject]:
    if not isinstance(order_public_id, str):
        return []
    payments = (
        select(Payment.public_id)
        .join(
            Order,
            (Order.project_id == Payment.project_id) & (Order.id == Payment.order_id),
        )
        .where(Order.project_id == project_id, Order.public_id == order_public_id)
    )
    payload = cast(func.convert_from(WebhookEvent.payload, "UTF8"), JSONB)
    payment = payload["payload"]["payment"]["entity"]
    refund = payload["payload"]["refund"]["entity"]
    events = session.scalars(
        select(WebhookEvent)
        .where(
            WebhookEvent.project_id == project_id,
            WebhookEvent.event_type.in_(
                (
                    "payment.authorized",
                    "payment.captured",
                    "payment.failed",
                    "refund.created",
                    "refund.processed",
                    "refund.failed",
                )
            ),
            or_(
                payment["order_id"].astext == order_public_id,
                refund["payment_id"].astext.in_(payments),
            ),
        )
        .order_by(WebhookEvent.created_at, WebhookEvent.id),
    )
    timeline = []
    for event in events:
        envelope = json.loads(event.payload)
        entities = envelope.get("payload", {})
        name = "refund" if event.event_type.startswith("refund.") else "payment"
        entity = entities.get(name, {}).get("entity", {})
        timeline.append(
            {
                "event_id": str(event.id),
                "event_type": event.event_type,
                "at": event.created_at.isoformat(),
                "entity_id": entity.get("id"),
                "status": entity.get("status"),
            }
        )
    return timeline


def delivery_timeline(
    session: Session, project_id: UUID, execution_id: UUID | None
) -> list[JsonObject]:
    if execution_id is None:
        return []
    rows = session.execute(
        select(WebhookDelivery, WebhookDeliveryAttempt)
        .outerjoin(
            WebhookDeliveryAttempt,
            (WebhookDeliveryAttempt.project_id == WebhookDelivery.project_id)
            & (WebhookDeliveryAttempt.delivery_id == WebhookDelivery.id),
        )
        .where(
            WebhookDelivery.project_id == project_id,
            WebhookDelivery.execution_id == execution_id,
        )
        .order_by(
            WebhookDelivery.created_at,
            WebhookDelivery.id,
            WebhookDeliveryAttempt.attempt_number,
        ),
    )
    deliveries: dict[UUID, JsonObject] = {}
    for delivery, attempt in rows:
        item = deliveries.setdefault(
            delivery.id,
            {
                "delivery_id": str(delivery.id),
                "event_id": str(delivery.event_id),
                "endpoint_id": str(delivery.endpoint_id),
                "status": delivery.status,
                "next_retry_at": delivery.next_retry_at.isoformat(),
                "attempts": [],
            },
        )
        if attempt is not None:
            item["attempts"].append(
                {
                    "number": attempt.attempt_number,
                    "at": attempt.created_at.isoformat(),
                    "http_status": attempt.http_status,
                    "duration_ms": attempt.duration_ms,
                    "error_code": attempt.error_code,
                }
            )
    return list(deliveries.values())


def reliability_report(session: Session, run: ReliabilityTestRun) -> JsonObject:
    source = run.result or {}
    cases = []
    latencies: list[int] = []
    for case in source.get("cases", []):
        evidence = case.get("evidence") or {}
        deliveries = delivery_timeline(
            session,
            run.project_id,
            evidence_uuid(evidence.get("scenario_execution_id")),
        )
        for delivery in deliveries:
            latencies.extend(
                attempt["duration_ms"]
                for attempt in delivery["attempts"]
                if attempt["http_status"] is not None
                and attempt["error_code"] is None
                and type(attempt["duration_ms"]) is int
            )
        cases.append(
            {
                **case,
                "diagnostics": diagnostics(case),
                "payment_timeline": payment_timeline(
                    session, run.project_id, evidence.get("order_id")
                ),
                "deliveries": deliveries,
            }
        )
    counts = Counter(case.get("status") for case in cases)
    return {
        "run_id": str(run.id),
        "suite_name": run.suite_name,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": source.get("duration_ms"),
        "summary": {
            "total": len(cases),
            **{state: counts[state] for state in CASE_STATES},
            "pass_rate": counts["passed"] / len(cases) if cases else None,
        },
        "delivery_latency_ms": {
            "count": len(latencies),
            "min": min(latencies, default=None),
            "median": median(latencies) if latencies else None,
            "max": max(latencies, default=None),
        },
        "cases": cases,
        "error": source.get("error"),
    }


def render_report(report: JsonObject) -> str:
    heading = escape(str(report["suite_name"]))
    status = escape(str(report["status"]))
    summary = report["summary"]
    rows = "".join(
        f'<tr><th scope="row">{escape(key.replace("_", " ").title())}</th>'
        f"<td>{escape(str(value)) if value is not None else 'Unavailable'}</td></tr>"
        for key, value in summary.items()
    )
    cases = "".join(
        f"<section><h2>{escape(case['name'])}</h2><p>{escape(case['status'])}</p>"
        f"<pre>{escape(json.dumps(case, indent=2, ensure_ascii=False))}</pre></section>"
        for case in report["cases"]
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>LocalPay report · {heading}</title><main><h1>{heading}</h1>"
        f"<p>Run status: {status}</p><table><caption>Test results</caption>{rows}</table>"
        f"{cases}</main></html>"
    )


def xml_text(value: str) -> str:
    return re.sub(
        r"[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "\ufffd", value
    )


def render_junit(run: ReliabilityTestRun) -> str:
    source = run.result or {}
    cases = source.get("cases", [])
    counts = Counter(case.get("status") for case in cases)
    root = Element(
        "testsuite",
        {
            "name": xml_text(run.suite_name),
            "tests": str(len(cases) or (1 if run.status == "error" else 0)),
            "failures": str(counts["failed"]),
            "errors": str(
                counts["error"] or (1 if not cases and run.status == "error" else 0)
            ),
            "skipped": str(counts["inconclusive"]),
            "time": f"{(source.get('duration_ms') or 0) / 1000:.3f}",
        },
    )
    for case in cases:
        step = SubElement(
            root,
            "testcase",
            {
                "name": xml_text(case["name"]),
                "classname": xml_text(run.suite_name),
                "time": f"{(case.get('duration_ms') or 0) / 1000:.3f}",
            },
        )
        if tag := {
            "failed": "failure",
            "error": "error",
            "inconclusive": "skipped",
        }.get(case["status"]):
            item = SubElement(step, tag, {"message": case["status"]})
            item.text = json.dumps(
                case.get("assertions") or case.get("evidence", {}), ensure_ascii=True
            )
    if not cases and run.status == "error":
        error_case = SubElement(
            root,
            "testcase",
            {"name": "Run execution", "classname": xml_text(run.suite_name)},
        )
        SubElement(
            error_case,
            "error",
            {"message": xml_text(str(source.get("error") or "Run failed"))},
        )
    return tostring(root, encoding="unicode", xml_declaration=True)
