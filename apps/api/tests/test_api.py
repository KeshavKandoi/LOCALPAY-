import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.settings import Settings
from app.main import app, create_app


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LOCALPAY_DATABASE_URL", "postgresql+psycopg://localpay@localhost:1/localpay"
    )
    monkeypatch.setenv("LOCALPAY_REDIS_URL", "redis://localhost:1/0")
    monkeypatch.setenv("LOCALPAY_DEPENDENCY_TIMEOUT_SECONDS", "1")


def test_application_import() -> None:
    assert app.title == "LocalPay"


def test_application_starts_and_health_responds() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_readiness_detects_unavailable_dependencies() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable",
            "dependencies": {"postgres": "down", "redis": "down"},
        }


def test_http_errors_use_the_common_envelope() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/missing")
        assert response.status_code == 404
        assert response.json() == {"error": {"code": "http_error"}}


def test_internal_errors_hide_exception_details() -> None:
    application = create_app(Settings())

    @application.get("/failure")
    def failure() -> None:
        raise RuntimeError("sensitive diagnostic")

    with TestClient(application) as client:
        response = client.get("/failure")
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "internal_error"}}
        assert response.headers["x-incident-id"]


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("DATABASE_URL", "sqlite:///localpay.db"),
        ("DATABASE_URL", "postgresql://localhost/localpay"),
        ("DATABASE_URL", "postgresql+psycopg://localhost,other/localpay"),
        ("REDIS_URL", "http://localhost"),
        ("REDIS_URL", "redis://localhost/not-a-database"),
        ("DEPENDENCY_TIMEOUT_SECONDS", "0"),
    ],
)
def test_invalid_environment_is_rejected(
    monkeypatch: MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(f"LOCALPAY_{variable}", value)
    with pytest.raises(ValidationError):
        Settings()
