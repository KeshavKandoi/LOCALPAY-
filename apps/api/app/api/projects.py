from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import IntegrityError

from app.api.auth import DatabaseSession, require_project, require_project_access
from app.models import Project
from app.services.credentials import (
    create_project,
    issue_credential,
    list_credentials,
    revoke_credential,
    rotate_credential,
)

admin_router = APIRouter(
    prefix="/localpay/admin/v1/projects",
    tags=["LocalPay administration"],
    dependencies=[Depends(require_project_access)],
)
project_router = APIRouter(prefix="/localpay/v1", tags=["LocalPay"])
ShortName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]+$"
    ),
]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Annotated[
        str, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    ]
    name: ShortName


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: ShortName


class CredentialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key_id: str
    label: str
    created_at: datetime
    revoked_at: datetime | None
    enabled: bool
    rotated_from_id: UUID | None


class IssuedCredential(CredentialView):
    secret: str


def get_project(session: DatabaseSession, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404)
    return project


@admin_router.post("", status_code=201)
def add_project(body: ProjectCreate, session: DatabaseSession) -> ProjectView:
    try:
        with session.begin():
            project = create_project(session, body.slug, body.name)
            result = ProjectView.model_validate(project)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(409) from None
        raise
    return result


@admin_router.post("/{project_id}/credentials", status_code=201)
def add_credential(
    project_id: UUID,
    body: CredentialCreate,
    response: Response,
    session: DatabaseSession,
) -> IssuedCredential:
    with session.begin():
        get_project(session, project_id)
        credential, secret = issue_credential(session, project_id, body.label)
        result = IssuedCredential(
            **CredentialView.model_validate(credential).model_dump(), secret=secret
        )
    response.headers["Cache-Control"] = "no-store"
    return result


@admin_router.get("/{project_id}/credentials")
def get_credentials(project_id: UUID, session: DatabaseSession) -> list[CredentialView]:
    get_project(session, project_id)
    return [
        CredentialView.model_validate(item)
        for item in list_credentials(session, project_id)
    ]


@admin_router.delete("/{project_id}/credentials/{credential_id}", status_code=204)
def disable_credential(
    project_id: UUID, credential_id: UUID, session: DatabaseSession
) -> Response:
    with session.begin():
        if not revoke_credential(session, project_id, credential_id):
            raise HTTPException(404)
    return Response(status_code=204)


@admin_router.post("/{project_id}/credentials/{credential_id}/rotate", status_code=201)
def replace_credential(
    project_id: UUID, credential_id: UUID, response: Response, session: DatabaseSession
) -> IssuedCredential:
    with session.begin():
        rotated = rotate_credential(session, project_id, credential_id)
        if rotated is None:
            raise HTTPException(404)
        credential, secret = rotated
        result = IssuedCredential(
            **CredentialView.model_validate(credential).model_dump(), secret=secret
        )
    response.headers["Cache-Control"] = "no-store"
    return result


@project_router.get("/project")
def current_project(
    project_id: Annotated[UUID, Depends(require_project)], session: DatabaseSession
) -> ProjectView:
    return ProjectView.model_validate(get_project(session, project_id))
