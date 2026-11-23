import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis import Redis
from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import build_engine
from app.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("LOCALPAY_RUN_INTEGRATION") != "1",
        reason="Set LOCALPAY_RUN_INTEGRATION=1 with isolated services running",
    ),
]


def test_postgresql_connection_and_applied_migration() -> None:
    engine = build_engine(Settings())
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == ("0001_baseline")
    finally:
        engine.dispose()


def test_redis_connection() -> None:
    with Redis.from_url(str(Settings().redis_url), socket_timeout=2) as redis:
        assert redis.ping() is True


def test_readiness_detects_available_dependencies() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "dependencies": {"postgres": "up", "redis": "up"},
        }


def test_readiness_identifies_postgresql_failure(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LOCALPAY_DATABASE_URL", "postgresql+psycopg://localpay@localhost:1/localpay"
    )
    with TestClient(create_app(Settings())) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"] == {"postgres": "down", "redis": "up"}


def test_celery_worker_processes_task() -> None:
    from app.workers.celery_app import celery_app

    assert not celery_app.conf.task_always_eager
    nonce = uuid4().hex
    result = celery_app.send_task("localpay.worker_probe", args=[nonce])
    assert result.get(timeout=15) == nonce
