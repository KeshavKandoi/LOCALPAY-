from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.session import get_session
from app.models import Project
from app.services.accounts import find_account
from app.services.credentials import authenticate_project

DatabaseSession = Annotated[Session, Depends(get_session)]

basic = HTTPBasic(realm="LocalPay", auto_error=False)
bearer = HTTPBearer(auto_error=False)


def require_project(
    session: DatabaseSession,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
) -> UUID:
    if credentials is not None:
        project_id = authenticate_project(
            session, credentials.username, credentials.password
        )
        if project_id is not None:
            return project_id
    raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="LocalPay"'})


def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    settings: Settings = request.app.state.settings
    token = settings.admin_token
    if token is not None and credentials is not None:
        candidate = credentials.credentials
        if (
            len(candidate) == 64
            and candidate.isascii()
            and compare_digest(candidate, token.get_secret_value())
        ):
            return
    raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})


def account_scope(request: Request) -> None:
    request.state.account_scope = True


def require_project_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if not getattr(request.state, "account_scope", False):
        require_admin(request, credentials)
        return
    with request.app.state.sessions() as session:
        account = find_account(session, credentials.credentials if credentials else "")
        if account is None:
            raise HTTPException(401)
        project_id = request.path_params.get("project_id")
        if project_id is None:
            raise HTTPException(404)
        try:
            project = session.get(Project, UUID(project_id))
        except ValueError:
            raise HTTPException(404) from None
        if project is None or project.owner_id != account.id:
            raise HTTPException(404)
