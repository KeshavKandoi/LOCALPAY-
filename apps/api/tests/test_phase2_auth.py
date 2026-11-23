import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.settings import Settings
from app.main import create_app
from app.services.credentials import KEY_PATTERN, SECRET_PATTERN, credential_verifier

ADMIN_URL = "/localpay/admin/v1/projects"
PROJECT_URL = "/localpay/v1/project"


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LOCALPAY_DATABASE_URL", "postgresql+psycopg://localpay@localhost:1/localpay"
    )
    monkeypatch.setenv("LOCALPAY_REDIS_URL", "redis://localhost:1/0")
    monkeypatch.delenv("LOCALPAY_ADMIN_TOKEN", raising=False)


def test_verifier_is_deterministic_and_bound_to_key_and_secret() -> None:
    key_id = "lp_test_" + "1" * 32
    secret = "lp_secret_" + "2" * 64
    assert KEY_PATTERN.fullmatch(key_id)
    assert SECRET_PATTERN.fullmatch(secret)
    digest = credential_verifier(key_id, secret)
    assert len(digest) == 32
    assert digest == credential_verifier(key_id, secret)
    assert digest != credential_verifier("lp_test_" + "3" * 32, secret)
    assert digest != credential_verifier(key_id, "lp_secret_" + "4" * 64)


@pytest.mark.parametrize("token", ["short", "g" * 64, "0" * 65, "0" * 63 + "Ａ"])
def test_invalid_admin_token_is_rejected_and_redacted(
    monkeypatch: MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("LOCALPAY_ADMIN_TOKEN", token)
    with pytest.raises(ValidationError) as captured:
        Settings()
    assert token not in str(captured.value)


def test_admin_is_disabled_without_a_token() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.post(
            ADMIN_URL,
            json={"slug": "example", "name": "Example"},
            headers={"Authorization": "Bearer " + "a" * 64},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", [None, "Basic invalid", "Bearer " + "a" * 64])
def test_basic_auth_challenges_without_querying_database(header: str | None) -> None:
    with TestClient(create_app(Settings())) as client:
        headers = {} if header is None else {"Authorization": header}
        response = client.get(PROJECT_URL, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="LocalPay"'
