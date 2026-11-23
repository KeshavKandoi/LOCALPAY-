from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from celery import Celery
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import build_engine
from app.services.delivery import claim_delivery, finish_delivery, scan, send
from app.services.payment_chaos import recover_payment_executions
from app.services.reliability import collect_runs, run_suite

settings = get_settings()
redis_url = str(settings.redis_url)
celery_app = Celery("localpay", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    broker_connection_retry_on_startup=True,
    result_expires=300,
    beat_schedule={
        "scan-webhook-deliveries": {"task": "localpay.scan_deliveries", "schedule": 2.0}
    },
    worker_prefetch_multiplier=1,
    task_default_queue=settings.celery_queue,
)


@celery_app.task(name="localpay.worker_probe")
def worker_probe(nonce: str) -> str:
    return nonce


@celery_app.task(name="localpay.scan_deliveries", ignore_result=True)
def scan_deliveries() -> None:
    engine = build_engine(settings)
    try:
        recover_payment_executions(engine)
        for project_id, delivery_id in scan(engine):
            celery_app.send_task(
                "localpay.deliver_webhook",
                args=[str(project_id), str(delivery_id)],
                retry=False,
            )
        for project_id, run_id in collect_runs(engine):
            celery_app.send_task(
                "localpay.run_reliability_suite",
                args=[str(project_id), str(run_id)],
                queue=f"{settings.celery_queue}.reliability",
                retry=False,
            )
    finally:
        engine.dispose()


@celery_app.task(
    name="localpay.deliver_webhook",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=15,
    time_limit=20,
)
def deliver_webhook(project_id: str, delivery_id: str) -> None:
    engine = build_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            claim = claim_delivery(
                session,
                UUID(project_id),
                UUID(delivery_id),
                datetime.now(UTC),
                settings,
            )
        if claim is None or claim.fault == "worker_interruption":
            return
        started = monotonic()
        result = send(claim, settings)
        duration_ms = int((monotonic() - started) * 1000)
        with Session(engine) as session, session.begin():
            finish_delivery(
                session, claim, result, datetime.now(UTC), duration_ms, settings
            )
    finally:
        engine.dispose()


@celery_app.task(
    name="localpay.run_reliability_suite",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=260,
    time_limit=280,
)
def run_reliability_suite(project_id: str, run_id: str) -> None:
    engine = build_engine(settings)
    try:
        run_suite(engine, settings, UUID(project_id), UUID(run_id))
    finally:
        engine.dispose()
