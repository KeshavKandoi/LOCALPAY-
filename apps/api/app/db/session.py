from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.settings import Settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        pool_timeout=settings.dependency_timeout_seconds,
        connect_args={"connect_timeout": settings.dependency_timeout_seconds},
        hide_parameters=True,
    )


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session
