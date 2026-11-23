import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api.dashboard import dashboard_router, projects_router
from app.api.orders import orders_router
from app.api.payment_chaos import payment_chaos_router
from app.api.payments import payments_router, simulation_router
from app.api.projects import admin_router, project_router
from app.api.refunds import refund_router, refund_simulation_router
from app.api.reliability import reliability_router
from app.api.reports import reports_router
from app.api.webhook_chaos import chaos_router
from app.api.webhooks import webhook_router
from app.core.errors import install_error_handling
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.session import build_engine

logger = logging.getLogger("localpay.health")
DependencyStatus = Literal["up", "down"]


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ready", "unavailable"]
    dependencies: dict[str, DependencyStatus]


def check_database(engine: Engine) -> DependencyStatus:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("PostgreSQL readiness failed type=%s", type(exc).__name__)
        return "down"
    return "up"


def check_redis(client: Redis) -> DependencyStatus:
    try:
        return "up" if client.ping() else "down"
    except RedisError as exc:
        logger.warning("Redis readiness failed type=%s", type(exc).__name__)
        return "down"


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        config = settings if settings is not None else get_settings()
        engine = build_engine(config)
        try:
            with Redis.from_url(
                str(config.redis_url),
                socket_connect_timeout=config.dependency_timeout_seconds,
                socket_timeout=config.dependency_timeout_seconds,
                retry=Retry(NoBackoff(), 0),
            ) as redis:
                app.state.settings = config
                app.state.engine = engine
                app.state.sessions = sessionmaker(bind=engine)
                app.state.redis = redis
                yield
        finally:
            engine.dispose()

    app = FastAPI(title="LocalPay", lifespan=lifespan)
    install_error_handling(app)
    app.include_router(admin_router)
    app.include_router(project_router)
    app.include_router(orders_router)
    app.include_router(payments_router)
    app.include_router(simulation_router)
    app.include_router(refund_router)
    app.include_router(refund_simulation_router)
    app.include_router(webhook_router)
    app.include_router(chaos_router)
    app.include_router(payment_chaos_router)
    app.include_router(reliability_router)
    app.include_router(reports_router)
    app.include_router(projects_router)
    app.include_router(dashboard_router)

    @app.get("/health")
    def health() -> Health:
        return Health()

    @app.get("/ready", responses={503: {"model": Readiness}})
    def readiness(request: Request, response: Response) -> Readiness:
        dependencies = {
            "postgres": check_database(request.app.state.engine),
            "redis": check_redis(request.app.state.redis),
        }
        if "down" in dependencies.values():
            response.status_code = 503
            return Readiness(status="unavailable", dependencies=dependencies)
        return Readiness(status="ready", dependencies=dependencies)

    return app


app = create_app()
