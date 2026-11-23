from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import DatabaseSession, require_admin
from app.api.projects import get_project
from app.models import (
    JsonObject,
    ReliabilitySuite,
    ReliabilityTestRun,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.test_definitions import SuiteDefinition, parse_suite_yaml

reliability_router = APIRouter(
    prefix="/localpay/admin/v1/projects/{project_id}",
    tags=["LocalPay reliability"],
    dependencies=[Depends(require_admin)],
)


class YamlSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yaml: Annotated[str, Field(max_length=65536)]


class SuiteView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    definition: SuiteDefinition
    created_at: datetime


class TestRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    suite_id: UUID | None
    suite_name: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: JsonObject | None


def suite_definition(body: SuiteDefinition | YamlSuite) -> SuiteDefinition:
    try:
        return parse_suite_yaml(body.yaml) if isinstance(body, YamlSuite) else body
    except ValueError as exc:
        raise HTTPException(422, detail="Invalid reliability suite definition") from exc


@reliability_router.post("/test-suites/validate")
def validate_suite(
    project_id: UUID, body: SuiteDefinition | YamlSuite, session: DatabaseSession
) -> SuiteDefinition:
    get_project(session, project_id)
    return suite_definition(body)


@reliability_router.post("/test-suites", status_code=201)
def create_suite(
    project_id: UUID,
    body: SuiteDefinition | YamlSuite,
    session: DatabaseSession,
) -> SuiteView:
    definition = suite_definition(body)
    try:
        with session.begin():
            get_project(session, project_id)
            for case in definition.tests:
                if case.endpoint_id is None:
                    continue
                endpoint = session.get(WebhookEndpoint, (project_id, case.endpoint_id))
                event_ids = set(
                    session.scalars(
                        select(WebhookEvent.id).where(
                            WebhookEvent.project_id == project_id,
                            WebhookEvent.id.in_(case.event_ids),
                        )
                    )
                )
                if endpoint is None or event_ids != case.event_ids:
                    raise HTTPException(404)
            suite = ReliabilitySuite(
                project_id=project_id,
                name=definition.name,
                definition=definition.model_dump(mode="json"),
            )
            session.add(suite)
            session.flush()
            return SuiteView.model_validate(suite)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(409) from None
        raise


@reliability_router.get("/test-suites")
def get_suites(
    project_id: UUID,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SuiteView]:
    get_project(session, project_id)
    rows = session.scalars(
        select(ReliabilitySuite)
        .where(
            ReliabilitySuite.project_id == project_id,
        )
        .order_by(ReliabilitySuite.created_at.desc(), ReliabilitySuite.id)
        .limit(count)
    )
    return [SuiteView.model_validate(row) for row in rows]


@reliability_router.post("/test-suites/{suite_id}/runs", status_code=202)
def start_run(
    project_id: UUID, suite_id: UUID, session: DatabaseSession
) -> TestRunView:
    with session.begin():
        suite = session.get(ReliabilitySuite, (project_id, suite_id))
        if suite is None:
            raise HTTPException(404)
        run = ReliabilityTestRun(
            project_id=project_id, suite_id=suite.id, suite_name=suite.name
        )
        session.add(run)
        session.flush()
        return TestRunView.model_validate(run)


@reliability_router.get("/test-runs")
def get_test_runs(
    project_id: UUID,
    session: DatabaseSession,
    count: Annotated[int, Query(ge=1, le=100)] = 50,
    suite_id: UUID | None = None,
) -> list[TestRunView]:
    query = select(ReliabilityTestRun).where(
        ReliabilityTestRun.project_id == project_id
    )
    if suite_id is not None:
        query = query.where(ReliabilityTestRun.suite_id == suite_id)
    rows = session.scalars(
        query.order_by(
            ReliabilityTestRun.created_at.desc(), ReliabilityTestRun.id
        ).limit(count)
    )
    return [TestRunView.model_validate(row) for row in rows]


@reliability_router.get("/test-runs/{run_id}")
def get_run(project_id: UUID, run_id: UUID, session: DatabaseSession) -> TestRunView:
    run = session.get(ReliabilityTestRun, (project_id, run_id))
    if run is None:
        raise HTTPException(404)
    return TestRunView.model_validate(run)


@reliability_router.get("/test-runs/{run_id}/json")
def get_run_json(project_id: UUID, run_id: UUID, session: DatabaseSession) -> Response:
    run = get_run(project_id, run_id, session)
    return Response(
        run.model_dump_json(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="localpay-run-{run.id}.json"'
        },
    )
