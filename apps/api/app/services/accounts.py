import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_bytes, token_urlsafe

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Account, AccountSession

SESSION_SECONDS = 8 * 60 * 60


def normalize_username(username: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,31}", username):
        raise ValueError("Use 3–32 letters, numbers, underscores or hyphens.")
    return username.lower()


def validate_password(password: str) -> None:
    if (
        not 12 <= len(password) <= 128
        or not password.strip()
        or re.search(r"[\ud800-\udfff]", password)
    ):
        raise ValueError("Use a password of 12–128 characters.")


def password_hash(password: str) -> str:
    return Argon2id(
        salt=token_bytes(16), length=32, iterations=2, lanes=1, memory_cost=19456
    ).derive_phc_encoded(password.encode())


def matches_password(password: str, encoded: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(password.encode(), encoded)
    except (InvalidKey, UnicodeError):
        return False
    return True


def digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def issue_session(session: Session, account: Account) -> str:
    now = datetime.now(UTC)
    session.execute(delete(AccountSession).where(AccountSession.expires_at <= now))
    token = "lp_session_" + token_urlsafe(32)
    session.add(
        AccountSession(
            token_hash=digest(token),
            account_id=account.id,
            expires_at=now + timedelta(seconds=SESSION_SECONDS),
        )
    )
    return token


def find_account(session: Session, token: str) -> Account | None:
    if not re.fullmatch(r"lp_session_[A-Za-z0-9_-]{43}", token):
        return None
    return session.scalar(
        select(Account)
        .join(AccountSession, AccountSession.account_id == Account.id)
        .where(
            AccountSession.token_hash == digest(token),
            AccountSession.expires_at > datetime.now(UTC),
        )
    )
