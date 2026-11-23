from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import BoundedSemaphore
from time import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.auth import DatabaseSession, bearer
from app.api.projects import ProjectCreate, ProjectView, ShortName
from app.models import Account, AccountSession, Project
from app.services.accounts import (
    digest,
    find_account,
    issue_session,
    matches_password,
    normalize_username,
    password_hash,
    validate_password,
)
from app.services.credentials import create_project

router = APIRouter(prefix="/localpay/account/v1", tags=["LocalPay accounts"])
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
empty_hash = password_hash("unused dummy account password")
password_slots = BoundedSemaphore(4)


@contextmanager
def password_work() -> Iterator[None]:
    if not password_slots.acquire(blocking=False):
        raise HTTPException(429, headers={"Retry-After": "1"})
    try:
        yield
    finally:
        password_slots.release()


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, Field(max_length=32)]
    password: SecretStr = Field(max_length=128)


class Signup(Login):
    confirm_password: SecretStr = Field(max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(max_length=128)
    password: SecretStr = Field(max_length=128)
    confirm_password: SecretStr = Field(max_length=128)


class AccountView(BaseModel):
    username: str


class SessionView(AccountView):
    token: str


class ProjectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortName


def token(credentials: Bearer) -> str:
    return credentials.credentials if credentials else ""


def account_for(session: DatabaseSession, credentials: Bearer) -> Account:
    account = find_account(session, token(credentials))
    if account is None:
        raise HTTPException(401)
    return account


def rate_limit(
    request: Request, action: str, identifier: str, limit: int, window: int
) -> None:
    now = int(time())
    elapsed = now % window
    key = f"localpay:account:{action}:{now // window}:{digest(identifier)}"
    try:
        with request.app.state.redis.pipeline() as pipe:
            count, _ = pipe.incr(key).expire(key, window + 1).execute()
    except RedisError:
        raise HTTPException(503) from None
    if count > limit:
        raise HTTPException(429, headers={"Retry-After": str(window - elapsed)})


def checked_password(password: SecretStr, confirm: SecretStr) -> str:
    value = password.get_secret_value()
    try:
        validate_password(value)
        if value != confirm.get_secret_value():
            raise ValueError("Passwords must match.")
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None
    return value


@router.post("/signup", status_code=201)
def signup(
    body: Signup, request: Request, response: Response, session: DatabaseSession
) -> SessionView:
    rate_limit(request, "signup", "instance", 30, 60)
    try:
        username = normalize_username(body.username)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None
    password = checked_password(body.password, body.confirm_password)
    with password_work():
        hashed = password_hash(password)
    try:
        with session.begin():
            account = Account(username=username, password_hash=hashed)
            session.add(account)
            session.flush()
            session_token = issue_session(session, account)
    except IntegrityError:
        raise HTTPException(
            409, detail="Could not register with those details."
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return SessionView(username=username, token=session_token)


@router.post("/login")
def login(
    body: Login, request: Request, response: Response, session: DatabaseSession
) -> SessionView:
    username = body.username.lower()
    rate_limit(request, "login", "instance", 120, 60)
    rate_limit(request, "login-name", username, 10, 60)
    with password_work(), session.begin():
        account = session.scalar(
            select(Account).where(Account.username == username).with_for_update()
        )
        valid = matches_password(
            body.password.get_secret_value(),
            account.password_hash if account else empty_hash,
        )
        if not valid or account is None:
            raise HTTPException(401, detail="Incorrect username or password.")
        session_token = issue_session(session, account)
    response.headers["Cache-Control"] = "no-store"
    return SessionView(username=username, token=session_token)


@router.get("/session")
def current_session(
    credentials: Bearer, session: DatabaseSession, response: Response
) -> AccountView:
    response.headers["Cache-Control"] = "no-store"
    return AccountView(username=account_for(session, credentials).username)


@router.delete("/session", status_code=204)
def logout(credentials: Bearer, session: DatabaseSession) -> None:
    with session.begin():
        session.execute(
            delete(AccountSession).where(
                AccountSession.token_hash == digest(token(credentials))
            )
        )


@router.patch("/password")
def change_password(
    body: PasswordChange,
    credentials: Bearer,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> AccountView:
    new_password = checked_password(body.password, body.confirm_password)
    with session.begin():
        account = account_for(session, credentials)
        rate_limit(request, "password", str(account.id), 10, 60)
        session.refresh(account, with_for_update=True)
        account_session = session.get(AccountSession, digest(token(credentials)))
        if account_session is None or account_session.expires_at <= datetime.now(UTC):
            raise HTTPException(401)
        with password_work():
            if not matches_password(
                body.current_password.get_secret_value(), account.password_hash
            ):
                raise HTTPException(403, detail="Incorrect current password.")
            account.password_hash = password_hash(new_password)
        session.execute(
            delete(AccountSession).where(
                AccountSession.account_id == account.id,
                AccountSession.token_hash != digest(token(credentials)),
            )
        )
        view = AccountView(username=account.username)
    response.headers["Cache-Control"] = "no-store"
    return view


@router.delete("/other-sessions", status_code=204)
def revoke_other_sessions(credentials: Bearer, session: DatabaseSession) -> None:
    with session.begin():
        account = account_for(session, credentials)
        session.execute(
            delete(AccountSession).where(
                AccountSession.account_id == account.id,
                AccountSession.token_hash != digest(token(credentials)),
            )
        )


@router.get("/projects")
def projects(credentials: Bearer, session: DatabaseSession) -> list[ProjectView]:
    account = account_for(session, credentials)
    rows = session.scalars(
        select(Project)
        .where(Project.owner_id == account.id)
        .order_by(Project.created_at, Project.id)
    )
    return [ProjectView.model_validate(project) for project in rows]


@router.post("/projects", status_code=201)
def add_project(
    body: ProjectCreate, credentials: Bearer, session: DatabaseSession
) -> ProjectView:
    try:
        with session.begin():
            account = account_for(session, credentials)
            project = create_project(session, body.slug, body.name)
            project.owner_id = account.id
            return ProjectView.model_validate(project)
    except IntegrityError:
        raise HTTPException(409) from None


def lookup_owned_project(
    project_id: UUID, credentials: Bearer, session: DatabaseSession
) -> Project:
    account = account_for(session, credentials)
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == account.id)
    )
    if project is None:
        raise HTTPException(404)
    return project


@router.get("/projects/{project_id}")
def owned_project(
    project_id: UUID, credentials: Bearer, session: DatabaseSession
) -> ProjectView:
    return ProjectView.model_validate(
        lookup_owned_project(project_id, credentials, session)
    )


@router.patch("/projects/{project_id}")
def edit_project(
    project_id: UUID, body: ProjectEdit, credentials: Bearer, session: DatabaseSession
) -> ProjectView:
    with session.begin():
        project = lookup_owned_project(project_id, credentials, session)
        project.name = body.name
        session.flush()
        return ProjectView.model_validate(project)
