import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import PostgresDsn, SecretStr
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from app.api import projects
from app.core.settings import Settings
from app.db.session import build_engine
from app.main import create_app
from app.models import (
    ApiCredential,
    AuditRecord,
    Base,
    Order,
    Payment,
    Project,
    Refund,
    ReliabilityTestRun,
    ScenarioExecution,
    SimulationScenario,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
    WebhookEvent,
)
from app.services.credentials import credential_verifier, issue_credential

ADMIN_URL = "/localpay/admin/v1/projects"
PROJECT_URL = "/localpay/v1/project"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("LOCALPAY_RUN_INTEGRATION") != "1",
        reason="Set LOCALPAY_RUN_INTEGRATION=1 with isolated services running",
    ),
]


@pytest.fixture
def schema_settings() -> Iterator[Settings]:
    config = Settings()
    schema = f"phase2_{uuid4().hex}"
    url = make_url(str(config.database_url)).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    control = build_engine(config)
    try:
        with control.begin() as connection:
            connection.execute(CreateSchema(schema))
        try:
            yield Settings(
                database_url=PostgresDsn(url.render_as_string(hide_password=False)),
                admin_token=SecretStr(uuid4().hex + uuid4().hex),
            )
        finally:
            with control.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
    finally:
        control.dispose()


@pytest.fixture
def database(schema_settings: Settings) -> Iterator[Engine]:
    engine = build_engine(schema_settings)
    try:
        with engine.connect() as connection:
            config = Config("alembic.ini", attributes={"connection": connection})
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def admin_client(schema_settings: Settings, database: Engine) -> Iterator[TestClient]:
    token = schema_settings.admin_token
    assert token is not None
    with TestClient(
        create_app(schema_settings),
        headers={"Authorization": f"Bearer {token.get_secret_value()}"},
    ) as client:
        yield client


def add_project(client: TestClient, slug: str) -> UUID:
    response = client.post(ADMIN_URL, json={"slug": slug, "name": slug.title()})
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def issue(client: TestClient, project_id: UUID) -> dict[str, Any]:
    response = client.post(
        f"{ADMIN_URL}/{project_id}/credentials", json={"label": "CI"}
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    result: dict[str, Any] = response.json()
    return result


def test_authentication_and_project_isolation(admin_client: TestClient) -> None:
    first = add_project(admin_client, "first")
    second = add_project(admin_client, "second")
    key = issue(admin_client, first)
    other = issue(admin_client, second)
    for project, credential in ((first, key), (second, other)):
        response = admin_client.get(
            PROJECT_URL, auth=(credential["key_id"], credential["secret"])
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(project)

    for auth in (
        (key["key_id"], other["secret"]),
        ("lp_test_" + "0" * 32, key["secret"]),
        ("rzp_live_example", "production"),
        ("rzp_test_example", "external-test"),
    ):
        response = admin_client.get(PROJECT_URL, auth=auth)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == 'Basic realm="LocalPay"'

    assert admin_client.get(PROJECT_URL).status_code == 401
    assert (
        admin_client.post(
            ADMIN_URL,
            json={"slug": "other", "name": "Other"},
            auth=(key["key_id"], key["secret"]),
        ).status_code
        == 401
    )
    assert (
        admin_client.post(
            ADMIN_URL,
            json={"slug": "other", "name": "Other"},
            headers={"Authorization": "Bearer " + "9" * 64},
        ).status_code
        == 401
    )
    credentials = admin_client.get(f"{ADMIN_URL}/{first}/credentials")
    assert credentials.status_code == 200
    assert [item["id"] for item in credentials.json()] == [key["id"]]
    assert (
        admin_client.delete(
            f"{ADMIN_URL}/{first}/credentials/{other['id']}"
        ).status_code
        == 404
    )
    assert (
        admin_client.get(
            PROJECT_URL, auth=(other["key_id"], other["secret"])
        ).status_code
        == 200
    )


def test_credentials_are_redacted_and_revoked_once(
    admin_client: TestClient, database: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = add_project(admin_client, "redaction")
    key = issue(admin_client, project_id)
    path = f"{ADMIN_URL}/{project_id}/credentials/{key['id']}"
    for _ in range(2):
        assert admin_client.delete(path).status_code == 204
    response = admin_client.get(PROJECT_URL, auth=(key["key_id"], key["secret"]))
    assert response.status_code == 401
    listed = admin_client.get(f"{ADMIN_URL}/{project_id}/credentials")
    assert listed.json()[0]["revoked_at"]
    assert "secret" not in listed.json()[0]
    assert "verifier" not in listed.json()[0]
    assert key["secret"] not in listed.text
    assert key["secret"] not in caplog.text
    with Session(database) as session:
        verifier = session.scalar(select(ApiCredential.verifier))
        assert verifier == credential_verifier(key["key_id"], key["secret"])
        assert isinstance(verifier, bytes)
        assert key["secret"].encode() not in verifier
        actions = session.scalars(select(AuditRecord.action)).all()
        assert sorted(actions) == [
            "credential.issued",
            "credential.revoked",
            "project.created",
        ]


def test_project_conflict_and_input_validation(admin_client: TestClient) -> None:
    add_project(admin_client, "duplicate")
    assert (
        admin_client.post(
            ADMIN_URL, json={"slug": "duplicate", "name": "Different"}
        ).status_code
        == 409
    )
    assert (
        admin_client.post(
            ADMIN_URL, json={"slug": "bad slug", "name": "Invalid"}
        ).status_code
        == 422
    )
    assert (
        admin_client.post(
            f"{ADMIN_URL}/{uuid4()}/credentials", json={"label": "Unknown"}
        ).status_code
        == 404
    )
    assert (
        admin_client.post(
            f"{ADMIN_URL}/{uuid4()}/credentials",
            json={"label": " ", "secret": "choose-my-own"},
        ).status_code
        == 422
    )

    assert (
        admin_client.post(
            ADMIN_URL, json={"slug": "nul", "name": "invalid\x00name"}
        ).status_code
        == 422
    )


def test_credential_and_audit_roll_back_together(
    admin_client: TestClient, database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = add_project(admin_client, "rollback")

    def fail_after_issue(
        session: Session, project: UUID, label: str
    ) -> tuple[ApiCredential, str]:
        issue_credential(session, project, label)
        session.flush()
        raise RuntimeError("failure after credential and audit inserts")

    monkeypatch.setattr(projects, "issue_credential", fail_after_issue)
    response = admin_client.post(
        f"{ADMIN_URL}/{project_id}/credentials", json={"label": "Rollback"}
    )
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    with Session(database) as session:
        assert session.scalars(select(ApiCredential)).all() == []
        assert session.scalars(select(AuditRecord.action)).all() == ["project.created"]
    monkeypatch.setattr(projects, "issue_credential", issue_credential)
    assert issue(admin_client, project_id)["secret"].startswith("lp_secret_")


def test_migrate_baseline_to_head_and_back(schema_settings: Settings) -> None:
    engine = build_engine(schema_settings)
    try:
        with engine.connect() as connection:
            config = Config("alembic.ini", attributes={"connection": connection})
            command.upgrade(config, "0001_baseline")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            connection.rollback()
            command.upgrade(config, "head")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0003_rotation_and_models"
            )
            assert set(inspect(connection).get_table_names()) == set(
                Base.metadata.tables
            ) | {"alembic_version"}
            connection.rollback()
            command.check(config)
            connection.rollback()
            command.downgrade(config, "0001_baseline")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            connection.rollback()
            command.upgrade(config, "head")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0003_rotation_and_models"
            )
    finally:
        engine.dispose()


def assert_rejected(session: Session, record: Base, sqlstate: str) -> None:
    with pytest.raises(IntegrityError) as rejected, session.begin_nested():
        session.add(record)
        session.flush()
    assert getattr(rejected.value.orig, "sqlstate", None) == sqlstate


def test_project_foreign_keys_and_financial_constraints(database: Engine) -> None:
    with Session(database) as session, session.begin():
        first = Project(slug="tenant-one", name="First")
        second = Project(slug="tenant-two", name="Second")
        session.add_all([first, second])
        session.flush()
        order = Order(project_id=first.id, amount=500, currency="INR")
        endpoint = WebhookEndpoint(project_id=first.id, url="http://example.test")
        event = WebhookEvent(
            project_id=first.id, event_type="payment.test", payload=b"{}"
        )
        scenario = SimulationScenario(project_id=first.id, name="sample")
        run = ReliabilityTestRun(project_id=first.id, suite_name="sample")
        session.add_all([order, endpoint, event, scenario, run])
        session.flush()
        payment = Payment(
            project_id=first.id, order_id=order.id, amount=500, currency="INR"
        )
        session.add(payment)
        session.flush()
        refund = Refund(
            project_id=first.id, payment_id=payment.id, amount=100, currency="INR"
        )
        delivery = WebhookDeliveryAttempt(
            project_id=first.id,
            event_id=event.id,
            endpoint_id=endpoint.id,
            attempt_number=1,
        )
        execution = ScenarioExecution(
            project_id=first.id, scenario_id=scenario.id, test_run_id=run.id
        )
        session.add_all([refund, delivery, execution])
        session.flush()
        assert payment.amount_captured == 0
        assert refund.created_at.tzinfo is not None
        assert session.get(Order, (second.id, order.id)) is None

        for invalid_reference in (
            Payment(
                project_id=second.id, order_id=order.id, amount=500, currency="INR"
            ),
            Refund(
                project_id=second.id, payment_id=payment.id, amount=100, currency="INR"
            ),
            Refund(project_id=first.id, payment_id=uuid4(), amount=100, currency="INR"),
            WebhookDeliveryAttempt(
                project_id=second.id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                attempt_number=1,
            ),
            ScenarioExecution(
                project_id=second.id, scenario_id=scenario.id, test_run_id=run.id
            ),
        ):
            assert_rejected(session, invalid_reference, "23503")

        for invalid_amount in (
            Order(project_id=first.id, amount=0, currency="INR"),
            Order(project_id=first.id, amount=500, amount_paid=501, currency="INR"),
            Payment(
                project_id=first.id,
                order_id=order.id,
                amount=500,
                amount_captured=501,
                currency="INR",
            ),
            Payment(
                project_id=first.id,
                order_id=order.id,
                amount=500,
                amount_refunded=1,
                currency="INR",
            ),
            Refund(
                project_id=first.id, payment_id=payment.id, amount=-1, currency="INR"
            ),
        ):
            assert_rejected(session, invalid_amount, "23514")

        key_id = "lp_test_" + "1" * 32
        session.add(
            ApiCredential(
                project_id=first.id, key_id=key_id, label="One", verifier=bytes(32)
            )
        )
        session.flush()
        assert_rejected(
            session,
            ApiCredential(
                project_id=second.id, key_id=key_id, label="Two", verifier=bytes(32)
            ),
            "23505",
        )
        assert_rejected(
            session,
            ApiCredential(
                project_id=first.id,
                key_id="rzp_live_rejected",
                label="External",
                verifier=bytes(32),
            ),
            "23514",
        )

        for duplicate in (
            WebhookEndpoint(project_id=first.id, url=endpoint.url),
            SimulationScenario(project_id=first.id, name=scenario.name),
            WebhookDeliveryAttempt(
                project_id=first.id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                attempt_number=1,
            ),
        ):
            assert_rejected(session, duplicate, "23505")


def test_rotation_is_atomic_and_scoped(
    admin_client: TestClient, database: Engine
) -> None:
    first = add_project(admin_client, "rotation-owner")
    other = add_project(admin_client, "rotation-other")
    key = issue(admin_client, first)
    assert (
        admin_client.post(
            f"{ADMIN_URL}/{other}/credentials/{key['id']}/rotate"
        ).status_code
        == 404
    )
    path = f"{ADMIN_URL}/{first}/credentials/{key['id']}/rotate"
    response = admin_client.post(path)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    replacement = response.json()
    assert replacement["rotated_from_id"] == key["id"]
    assert replacement["enabled"]
    assert replacement["label"] == key["label"]
    assert admin_client.post(path).status_code == 404
    assert (
        admin_client.get(PROJECT_URL, auth=(key["key_id"], key["secret"])).status_code
        == 401
    )
    new_auth = (replacement["key_id"], replacement["secret"])
    assert admin_client.get(PROJECT_URL, auth=new_auth).json()["id"] == str(first)
    with Session(database) as session, session.begin():
        project = session.get(Project, first)
        assert project is not None
        project.status = "disabled"
    assert admin_client.get(PROJECT_URL, auth=new_auth).status_code == 401


def test_supplement_migrates_existing_money_records(schema_settings: Settings) -> None:
    engine = build_engine(schema_settings)
    try:
        with engine.connect() as connection:
            config = Config("alembic.ini", attributes={"connection": connection})
            command.upgrade(config, "0002_project_models")
            ids = dict(
                zip(
                    ("project", "order", "payment", "refund"),
                    (uuid4() for _ in range(4)),
                    strict=True,
                )
            )
            statements = (
                "INSERT INTO projects (id, slug, name) VALUES (:project, 'existing', 'Existing')",
                "INSERT INTO orders (project_id, id, amount, amount_paid, currency) "
                "VALUES (:project, :order, 200, 100, 'USD')",
                "INSERT INTO payments (project_id, id, order_id, amount, amount_captured, currency) "
                "VALUES (:project, :payment, :order, 100, 100, 'USD')",
                "INSERT INTO refunds (project_id, id, payment_id, amount) "
                "VALUES (:project, :refund, :payment, 10)",
            )
            with connection.begin():
                for statement in statements:
                    connection.execute(text(statement), ids)
            command.upgrade(config, "head")
            assert connection.scalar(text("SELECT amount_due FROM orders")) == 100
            assert (
                connection.scalar(text("SELECT amount_authorized FROM payments")) == 100
            )
            assert connection.scalar(text("SELECT currency FROM refunds")) == "USD"
    finally:
        engine.dispose()
