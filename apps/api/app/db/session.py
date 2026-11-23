from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.settings import Settings


def build_engine(settings: Settings) -> Engine:
    url = make_url(str(settings.database_url))
    options = url.normalized_query.get("options", ())
    driver_options = " ".join(
        (*options, "-c statement_timeout=15000 -c lock_timeout=5000")
    )
    return create_engine(
        url.difference_update_query(["options"]),
        pool_pre_ping=True,
        pool_timeout=settings.dependency_timeout_seconds,
        connect_args={
            "connect_timeout": settings.dependency_timeout_seconds,
            "options": driver_options,
        },
        hide_parameters=True,
    )


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session
