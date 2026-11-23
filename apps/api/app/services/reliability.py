import logging
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import (
    JsonObject,
    ReliabilitySuite,
    ReliabilityTestRun,
    ScenarioExecution,
    SimulationScenario,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.assertions import evaluate, verify_application
from app.services.payment_chaos import (
    PaymentChaosType,
    create_execution,
    execute_transaction_case,
)
from app.services.test_definitions import SuiteDefinition, TestCase
from app.services.webhook_chaos import WebhookChaos, enqueue_chaos

logger = logging.getLogger("localpay.reliability")


def collect_runs(engine: Engine) -> list[tuple[UUID, UUID]]:
    with Session(engine) as session, session.begin():
        stale = session.scalars(
            select(ReliabilityTestRun)
            .where(
                ReliabilityTestRun.suite_id.is_not(None),
                ReliabilityTestRun.status == "running",
                ReliabilityTestRun.started_at
                < datetime.now(UTC) - timedelta(minutes=6),
            )
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        for run in stale:
            run.status = "error"
            run.finished_at = datetime.now(UTC)
            run.result = {"cases": [], "error": "worker_interrupted"}
        rows = session.execute(
            select(ReliabilityTestRun.project_id, ReliabilityTestRun.id)
            .where(
                ReliabilityTestRun.suite_id.is_not(None),
                ReliabilityTestRun.status == "pending",
            )
            .order_by(ReliabilityTestRun.created_at)
            .limit(50)
        )
        return [(row[0], row[1]) for row in rows]


def begin_run(engine: Engine, project_id: UUID, run_id: UUID) -> JsonObject | None:
    with Session(engine) as session, session.begin():
        run = session.get(
            ReliabilityTestRun, (project_id, run_id), with_for_update=True
        )
        if run is None or run.suite_id is None or run.status != "pending":
            return None
        suite = session.get(ReliabilitySuite, (project_id, run.suite_id))
        if suite is None:
            raise RuntimeError("Test suite is missing")
        run.status = "running"
        run.started_at = datetime.now(UTC)
        return suite.definition


def execute_webhook_case(
    engine: Engine,
    project_id: UUID,
    run_id: UUID,
    case: TestCase,
) -> JsonObject:
    with Session(engine) as session, session.begin():
        endpoint = session.get(WebhookEndpoint, (project_id, case.endpoint_id))
        events = list(
            session.scalars(
                select(WebhookEvent).where(
                    WebhookEvent.project_id == project_id,
                    WebhookEvent.id.in_(case.event_ids),
                )
            )
        )
        if (
            endpoint is None
            or not endpoint.enabled
            or len(events) != len(case.event_ids)
        ):
            raise LookupError("Webhook inputs are missing")
        config = case.config or WebhookChaos(
            duplicate_count=2 if case.scenario == "webhook.duplicate" else 1
        )
        scenario = SimulationScenario(
            project_id=project_id,
            name=f"run-{run_id.hex}-{uuid4().hex}",
            scenario_type="webhook.chaos",
            configuration=config.model_dump(),
        )
        session.add(scenario)
        session.flush()
        execution = enqueue_chaos(session, project_id, scenario, endpoint, events)
        execution.test_run_id = run_id
        execution_id = execution.id
    deadline = monotonic() + 15
    while monotonic() < deadline:
        with Session(engine) as session:
            current_execution = session.get(
                ScenarioExecution, (project_id, execution_id)
            )
            if current_execution is None:
                raise RuntimeError("Webhook execution is missing")
            if current_execution.status != "running":
                rows = session.execute(
                    select(
                        WebhookDeliveryAttempt.http_status,
                        WebhookDeliveryAttempt.attempt_number,
                    )
                    .join(
                        WebhookDelivery,
                        (
                            WebhookDelivery.project_id
                            == WebhookDeliveryAttempt.project_id
                        )
                        & (WebhookDelivery.id == WebhookDeliveryAttempt.delivery_id),
                    )
                    .where(
                        WebhookDelivery.project_id == project_id,
                        WebhookDelivery.execution_id == execution_id,
                        WebhookDeliveryAttempt.error_code.is_(None),
                    )
                    .order_by(
                        WebhookDeliveryAttempt.created_at, WebhookDeliveryAttempt.id
                    )
                )
                observed = [
                    (status, attempt) for status, attempt in rows if status is not None
                ]
                statuses = [status for status, _ in observed]
                return {
                    "scenario_execution_id": str(execution_id),
                    "webhook_configuration": config.model_dump(),
                    "event_count": len(case.event_ids),
                    "only_invalid_signatures_observed": bool(observed)
                    and config.failure_mode == "invalid_signature"
                    and all(
                        attempt <= config.failure_attempts for _, attempt in observed
                    ),
                    "scenario_passed": current_execution.status == "succeeded",
                    "delivery_count": len(statuses),
                    "http_statuses": statuses,
                    "received_http_status": statuses[-1] if statuses else None,
                }
        sleep(0.2)
    return {"scenario_execution_id": str(execution_id), "waiting_timed_out": True}


def execute_payment_case(
    engine: Engine,
    project_id: UUID,
    run_id: UUID,
    case: TestCase,
    scenario: PaymentChaosType,
) -> JsonObject:
    with Session(engine) as session, session.begin():
        execution = create_execution(session, project_id, scenario)
        execution.test_run_id = run_id
        execution_id = execution.id
    try:
        evidence = execute_transaction_case(
            engine, project_id, execution_id, scenario, case.amount
        )
    except Exception as exc:
        finish_case(
            engine, project_id, execution_id, False, {"error_type": type(exc).__name__}
        )
        raise
    passed = bool(evidence["passed"])
    finish_case(engine, project_id, execution_id, passed, evidence)
    return {
        **evidence,
        "scenario_passed": passed,
        "scenario_execution_id": str(execution_id),
    }


def finish_case(
    engine: Engine,
    project_id: UUID,
    execution_id: UUID,
    passed: bool,
    evidence: JsonObject,
) -> None:
    with Session(engine) as session, session.begin():
        execution = session.get(ScenarioExecution, (project_id, execution_id))
        if execution is None:
            raise RuntimeError("Payment execution is missing")
        execution.status = "succeeded" if passed else "failed"
        execution.finished_at = datetime.now(UTC)
        execution.result = {**(execution.result or {}), **evidence}


def summarize(statuses: list[str]) -> str:
    return next(
        (
            status
            for status in ("error", "failed", "inconclusive")
            if status in statuses
        ),
        "passed",
    )


def run_suite(
    engine: Engine, settings: Settings, project_id: UUID, run_id: UUID
) -> None:
    raw = begin_run(engine, project_id, run_id)
    if raw is None:
        return
    started = monotonic()
    cases: list[JsonObject] = []
    suite = SuiteDefinition.model_validate(raw)
    for case in suite.tests:
        case_started = monotonic()
        try:
            if isinstance(case.scenario, PaymentChaosType):
                evidence = execute_payment_case(
                    engine, project_id, run_id, case, case.scenario
                )
            else:
                evidence = execute_webhook_case(engine, project_id, run_id, case)
            if any(
                assertion.type.startswith("application_")
                for assertion in case.assertions
            ):
                target = (
                    str(suite.verification_url)
                    if suite.verification_url is not None
                    else None
                )
                evidence.update(
                    verify_application(target, settings, run_id, case.name, evidence)
                )
            assertions = evaluate(case.assertions, evidence)
            status = summarize([row["status"] for row in assertions])
        except Exception as exc:
            logger.error(
                "Reliability case failed run=%s error=%s", run_id, type(exc).__name__
            )
            status = "error"
            evidence = {"error_type": type(exc).__name__}
            assertions = []
        cases.append(
            {
                "name": case.name,
                "scenario": case.scenario,
                "status": status,
                "evidence": evidence,
                "assertions": assertions,
                "duration_ms": int((monotonic() - case_started) * 1000),
            }
        )
    with Session(engine) as session, session.begin():
        run = session.get(
            ReliabilityTestRun, (project_id, run_id), with_for_update=True
        )
        if run is None:
            raise RuntimeError("Reliability test run is missing")
        if run.status == "running":
            run.status = summarize([case["status"] for case in cases])
            run.finished_at = datetime.now(UTC)
            run.result = {
                "cases": cases,
                "duration_ms": int((monotonic() - started) * 1000),
            }
