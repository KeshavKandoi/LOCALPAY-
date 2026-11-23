import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
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
from app.services.payments import capture_payment

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
                == ScriptDirectory.from_config(config).get_current_head()
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
                == ScriptDirectory.from_config(config).get_current_head()
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


def test_order_contract_persistence_and_tenant_isolation(
    admin_client: TestClient, database: Engine
) -> None:
    owner = add_project(admin_client, "orders-owner")
    outsider = add_project(admin_client, "orders-outsider")
    owner_key = issue(admin_client, owner)
    outsider_key = issue(admin_client, outsider)
    auth = (owner_key["key_id"], owner_key["secret"])
    other_auth = (outsider_key["key_id"], outsider_key["secret"])
    request = {
        "amount": 5000,
        "currency": "INR",
        "receipt": "reference-a",
        "notes": {"cart": "A"},
    }
    created = admin_client.post("/v1/orders", auth=auth, json=request)
    assert created.status_code == 200, created.text
    order = created.json()
    assert order == {
        **request,
        "id": order["id"],
        "entity": "order",
        "amount_paid": 0,
        "amount_due": 5000,
        "offer_id": None,
        "status": "created",
        "attempts": 0,
        "created_at": order["created_at"],
    }
    assert order["id"].startswith("order_") and len(order["id"]) == 20
    assert isinstance(order["created_at"], int)
    path = f"/v1/orders/{order['id']}"
    assert admin_client.get(path, auth=auth).json() == order
    assert (
        admin_client.get(path, auth=other_auth).json()
        == admin_client.get("/v1/orders/order_missing000000", auth=other_auth).json()
    )
    assert admin_client.get(path, auth=other_auth).status_code == 400
    assert admin_client.post("/v1/orders", auth=auth, json=request).status_code == 400
    assert (
        admin_client.post("/v1/orders", auth=other_auth, json=request).status_code
        == 200
    )
    with Session(database) as session:
        stored = session.scalar(select(Order).where(Order.project_id == owner))
        assert stored is not None and stored.public_id == order["id"]
        assert stored.amount_due == 5000


def test_order_list_filters_and_validation(admin_client: TestClient) -> None:
    owner = add_project(admin_client, "order-lists")
    key = issue(admin_client, owner)
    auth = (key["key_id"], key["secret"])
    path = "/v1/orders"
    for receipt in ("cart-01", "cart-02", "other"):
        response = admin_client.post(
            path, auth=auth, json={"amount": 100, "currency": "INR", "receipt": receipt}
        )
        assert response.status_code == 200, response.text
        assert response.json()["notes"] == []
    page = admin_client.get(
        path,
        auth=auth,
        params={"count": 1, "skip": 1, "receipt": "cart", "authorized": 0},
    )
    assert page.status_code == 200
    assert page.json()["entity"] == "collection"
    assert page.json()["count"] == 1
    assert page.json()["items"][0]["receipt"] == "cart-01"
    timestamp = page.json()["items"][0]["created_at"]
    dated = admin_client.get(
        path, auth=auth, params={"from": timestamp, "to": timestamp}
    )
    assert dated.status_code == 200 and dated.json()["count"] >= 1
    assert (
        admin_client.get(path, auth=auth, params={"authorized": 1}).json()["items"]
        == []
    )
    credentials = admin_client.get(path)
    assert (
        credentials.status_code == 400 and credentials.json()["error"]["reason"] == "NA"
    )
    for request in (
        {},
        {"amount": -1, "currency": "INR"},
        {"amount": 0, "currency": "INR"},
        {"amount": 100.0, "currency": "INR"},
        {"amount": "100", "currency": "INR"},
        {"amount": 100, "currency": "XYZ"},
        {"amount": 101, "currency": "KWD"},
        {"amount": 100, "currency": "INR", "receipt": "x" * 41},
        {"amount": 100, "currency": "INR", "notes": {str(i): "x" for i in range(16)}},
    ):
        failure = admin_client.post(path, auth=auth, json=request)
        assert failure.status_code == 400
        assert failure.json()["error"]["code"] == "BAD_REQUEST_ERROR"
    malformed = admin_client.post(
        path,
        auth=auth,
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 400
    assert admin_client.get(path, auth=auth, params={"count": 101}).status_code == 400


def test_payment_scenarios_and_capture_contract(admin_client: TestClient) -> None:
    project_id = add_project(admin_client, "payment-contract")
    key = issue(admin_client, project_id)
    auth = (key["key_id"], key["secret"])
    order = admin_client.post(
        "/v1/orders", auth=auth, json={"amount": 600, "currency": "INR"}
    ).json()
    for scenario, expected_status, state in (
        ("payment.failed", 201, "failed"),
        ("payment.insufficient_funds", 201, "failed"),
        ("payment.authorization_failed", 201, "failed"),
        ("payment.capture_failed", 201, "authorized"),
        ("payment.timeout", 504, "created"),
        ("payment.network_interruption", 503, "created"),
        ("payment.success", 201, "authorized"),
    ):
        response = admin_client.post(
            "/localpay/v1/simulations/payments",
            auth=auth,
            json={"scenario": scenario, "order_id": order["id"]},
        )
        assert response.status_code == expected_status, response.text
        payment = response.json()
        assert payment["status"] == state
        path = f"/v1/payments/{payment['id']}"
        assert admin_client.get(path, auth=auth).json() == payment
        if scenario != "payment.success":
            assert (
                admin_client.post(
                    f"{path}/capture",
                    auth=auth,
                    json={"amount": 600, "currency": "INR"},
                ).status_code
                == 400
            )
    path = f"/v1/payments/{payment['id']}"
    for request in (
        {"amount": 500, "currency": "INR"},
        {"amount": 600, "currency": "USD"},
    ):
        assert (
            admin_client.post(f"{path}/capture", auth=auth, json=request).status_code
            == 400
        )
    assert (
        admin_client.get("/v1/orders", auth=auth, params={"authorized": 1}).json()[
            "count"
        ]
        == 1
    )
    result = admin_client.post(
        f"{path}/capture", auth=auth, json={"amount": 600, "currency": "INR"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "captured"
    assert (
        admin_client.post(
            f"{path}/capture", auth=auth, json={"amount": 600, "currency": "INR"}
        ).status_code
        == 400
    )
    assert admin_client.get(f"/v1/orders/{order['id']}", auth=auth).json() == {
        **order,
        "amount_paid": 600,
        "amount_due": 0,
        "status": "paid",
        "attempts": 7,
    }
    outsider = issue(admin_client, add_project(admin_client, "payment-outsider"))
    other_auth = (outsider["key_id"], outsider["secret"])
    assert admin_client.get(path, auth=other_auth).status_code == 400


def test_concurrent_captures_cannot_overpay_order(
    admin_client: TestClient, schema_settings: Settings, database: Engine
) -> None:
    project_id = add_project(admin_client, "concurrent-capture")
    key = issue(admin_client, project_id)
    auth = (key["key_id"], key["secret"])
    order = admin_client.post(
        "/v1/orders", auth=auth, json={"amount": 600, "currency": "INR"}
    ).json()
    payment_ids = [
        admin_client.post(
            "/localpay/v1/simulations/payments",
            auth=auth,
            json={"order_id": order["id"]},
        ).json()["id"]
        for _ in range(2)
    ]
    with (
        pytest.raises(RuntimeError, match="rollback"),
        Session(database) as session,
        session.begin(),
    ):
        capture_payment(session, project_id, payment_ids[0], 600, "INR")
        raise RuntimeError("rollback")
    assert (
        admin_client.get(f"/v1/orders/{order['id']}", auth=auth).json()["amount_paid"]
        == 0
    )
    barrier = Barrier(2)

    def capture_one(payment_id: str) -> int:
        with TestClient(create_app(schema_settings)) as client:
            barrier.wait(timeout=10)
            return client.post(
                f"/v1/payments/{payment_id}/capture",
                auth=auth,
                json={"amount": 600, "currency": "INR"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(capture_one, payment_ids)) == [200, 400]
    record = admin_client.get(f"/v1/orders/{order['id']}", auth=auth).json()
    assert record["amount_paid"] == 600 and record["amount_due"] == 0


def captured_payment(
    client: TestClient, auth: tuple[str, str], amount: int = 600
) -> str:
    order = client.post(
        "/v1/orders", auth=auth, json={"amount": amount, "currency": "INR"}
    ).json()
    payment = client.post(
        "/localpay/v1/simulations/payments",
        auth=auth,
        json={"order_id": order["id"]},
    ).json()
    response = client.post(
        f"/v1/payments/{payment['id']}/capture",
        auth=auth,
        json={"amount": amount, "currency": "INR"},
    )
    assert response.status_code == 200, response.text
    payment_id: str = payment["id"]
    return payment_id


def test_partial_and_full_refund_with_idempotency(
    admin_client: TestClient, database: Engine
) -> None:
    key = issue(admin_client, add_project(admin_client, "refund-contract"))
    auth = (key["key_id"], key["secret"])
    payment_id = captured_payment(admin_client, auth)
    path = f"/v1/payments/{payment_id}"
    header = {"X-Refund-Idempotency": "unique-refund-1"}
    first = admin_client.post(
        f"{path}/refund", auth=auth, json={"amount": 200}, headers=header
    )
    assert first.status_code == 200, first.text
    refund = first.json()
    assert refund["status"] == "processed" and refund["amount"] == 200
    assert (
        admin_client.post(
            f"{path}/refund", auth=auth, json={"amount": 200}, headers=header
        ).json()
        == refund
    )
    assert (
        admin_client.post(
            f"{path}/refund", auth=auth, json={"amount": 201}, headers=header
        ).status_code
        == 409
    )
    assert (
        admin_client.get(f"{path}/refunds/{refund['id']}", auth=auth).json() == refund
    )
    assert admin_client.get(f"/v1/refunds/{refund['id']}", auth=auth).json() == refund
    assert admin_client.get(path, auth=auth).json()["refund_status"] == "partial"
    assert (
        admin_client.post(f"{path}/refund", auth=auth, json={"amount": 401}).status_code
        == 400
    )
    assert (
        admin_client.post(f"{path}/refund", auth=auth, json={"amount": 100}).status_code
        == 200
    )
    final = admin_client.post(f"{path}/refund", auth=auth, json={})
    assert final.status_code == 200 and final.json()["amount"] == 300
    assert admin_client.post(f"{path}/refund", auth=auth, json={}).status_code == 400
    assert admin_client.get(path, auth=auth).json()["status"] == "refunded"
    assert admin_client.get(f"{path}/refunds", auth=auth).json()["count"] == 3
    outsider = issue(admin_client, add_project(admin_client, "refund-outsider"))
    assert (
        admin_client.get(
            f"/v1/refunds/{refund['id']}", auth=(outsider["key_id"], outsider["secret"])
        ).status_code
        == 400
    )
    with Session(database) as session:
        events = session.scalars(select(WebhookEvent)).all()
        assert len(events) == 6
        assert {event.event_type for event in events} == {
            "refund.created",
            "refund.processed",
        }


def test_pending_refund_releases_balance_when_failed(admin_client: TestClient) -> None:
    key = issue(admin_client, add_project(admin_client, "refund-reservation"))
    auth = (key["key_id"], key["secret"])
    payment_id = captured_payment(admin_client, auth)
    path = f"/v1/payments/{payment_id}"
    pending = admin_client.post(
        f"/localpay/v1/simulations/payments/{payment_id}/refunds",
        auth=auth,
        json={"amount": 500, "reason": "Simulation"},
    )
    assert pending.status_code == 201, pending.text
    refund = pending.json()
    assert refund["status"] == "pending"
    assert (
        admin_client.post(f"{path}/refund", auth=auth, json={"amount": 101}).status_code
        == 400
    )
    resolve = f"/localpay/v1/simulations/refunds/{refund['id']}/resolve"
    assert (
        admin_client.post(resolve, auth=auth, json={"outcome": "failed"}).json()[
            "status"
        ]
        == "failed"
    )
    assert (
        admin_client.post(resolve, auth=auth, json={"outcome": "processed"}).status_code
        == 409
    )
    assert (
        admin_client.post(f"{path}/refund", auth=auth, json={}).json()["amount"] == 600
    )


def test_concurrent_refunds_cannot_exceed_capture(
    admin_client: TestClient, schema_settings: Settings
) -> None:
    key = issue(admin_client, add_project(admin_client, "concurrent-refund"))
    auth = (key["key_id"], key["secret"])
    payment_id = captured_payment(admin_client, auth)
    path = f"/v1/payments/{payment_id}"
    barrier = Barrier(2)

    def refund_one(amount: int) -> int:
        with TestClient(create_app(schema_settings)) as client:
            barrier.wait(timeout=10)
            return client.post(
                f"{path}/refund", auth=auth, json={"amount": amount}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(refund_one, [500, 500])) == [200, 400]
    assert admin_client.get(path, auth=auth).json()["amount_refunded"] == 500


def test_failed_and_uncaptured_payments_cannot_be_refunded(
    admin_client: TestClient,
) -> None:
    key = issue(admin_client, add_project(admin_client, "refund-ineligible"))
    auth = (key["key_id"], key["secret"])
    order = admin_client.post(
        "/v1/orders", auth=auth, json={"amount": 600, "currency": "INR"}
    ).json()
    for scenario in ("payment.failed", "payment.success"):
        payment = admin_client.post(
            "/localpay/v1/simulations/payments",
            auth=auth,
            json={"order_id": order["id"], "scenario": scenario},
        ).json()
        assert (
            admin_client.post(
                f"/v1/payments/{payment['id']}/refund", auth=auth, json={}
            ).status_code
            == 400
        )
