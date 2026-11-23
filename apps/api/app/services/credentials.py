from datetime import UTC, datetime
from hashlib import sha256
from re import compile
from secrets import compare_digest, token_hex
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import ApiCredential, AuditRecord, Project

KEY_PATTERN = compile(r"lp_test_[0-9a-f]{32}")
SECRET_PATTERN = compile(r"lp_secret_[0-9a-f]{64}")


def credential_verifier(key_id: str, secret: str) -> bytes:
    return sha256(f"localpay-api:{key_id}:{secret}".encode("ascii")).digest()


def authenticate_project(session: Session, key_id: str, secret: str) -> UUID | None:
    if (
        KEY_PATTERN.fullmatch(key_id) is None
        or SECRET_PATTERN.fullmatch(secret) is None
    ):
        return None
    row = session.execute(
        select(
            ApiCredential.project_id, ApiCredential.verifier, ApiCredential.revoked_at
        )
        .join(Project, Project.id == ApiCredential.project_id)
        .where(ApiCredential.key_id == key_id, Project.status == "active")
    ).one_or_none()
    candidate = credential_verifier(key_id, secret)
    matches = compare_digest(candidate, row.verifier if row else bytes(32))
    if row is not None and matches and row.revoked_at is None:
        project_id: UUID = row.project_id
        return project_id
    return None


def create_project(session: Session, slug: str, name: str) -> Project:
    project = Project(slug=slug, name=name)
    session.add(project)
    session.flush()
    record_admin_action(session, project.id, "project.created")
    return project


def issue_credential(
    session: Session,
    project_id: UUID,
    label: str,
    *,
    rotated_from_id: UUID | None = None,
) -> tuple[ApiCredential, str]:
    key_id = f"lp_test_{token_hex(16)}"
    secret = f"lp_secret_{token_hex(32)}"
    credential = ApiCredential(
        project_id=project_id,
        key_id=key_id,
        label=label,
        rotated_from_id=rotated_from_id,
        verifier=credential_verifier(key_id, secret),
    )
    session.add(credential)
    session.flush()
    record_admin_action(session, project_id, "credential.issued", credential.id)
    return credential, secret


def rotate_credential(
    session: Session, project_id: UUID, credential_id: UUID
) -> tuple[ApiCredential, str] | None:
    label = session.scalar(
        update(ApiCredential)
        .where(
            ApiCredential.project_id == project_id,
            ApiCredential.id == credential_id,
            ApiCredential.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(ApiCredential.label)
    )
    if label is None:
        return None
    replacement = issue_credential(
        session, project_id, label, rotated_from_id=credential_id
    )
    record_admin_action(session, project_id, "credential.rotated", credential_id)
    return replacement


def list_credentials(session: Session, project_id: UUID) -> list[ApiCredential]:
    return list(
        session.scalars(
            select(ApiCredential)
            .where(ApiCredential.project_id == project_id)
            .order_by(ApiCredential.created_at, ApiCredential.id)
        )
    )


def revoke_credential(session: Session, project_id: UUID, credential_id: UUID) -> bool:
    revoked = session.scalar(
        update(ApiCredential)
        .where(
            ApiCredential.project_id == project_id,
            ApiCredential.id == credential_id,
            ApiCredential.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(ApiCredential.id)
    )
    if revoked is not None:
        record_admin_action(session, project_id, "credential.revoked", credential_id)
        return True
    return session.get(ApiCredential, (project_id, credential_id)) is not None


def record_admin_action(
    session: Session, project_id: UUID, action: str, credential_id: UUID | None = None
) -> None:
    session.add(
        AuditRecord(
            project_id=project_id,
            actor="admin",
            action=action,
            credential_id=credential_id,
        )
    )
