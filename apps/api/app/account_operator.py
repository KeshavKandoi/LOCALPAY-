import argparse
import sys
from getpass import getpass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import build_engine
from app.models import Account, AccountSession, Project
from app.services.accounts import normalize_username, password_hash, validate_password


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage LocalPay accounts as a database operator."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-unowned-projects")
    claim = commands.add_parser("claim-project")
    claim.add_argument("slug")
    claim.add_argument("username")
    reset = commands.add_parser("reset-password")
    reset.add_argument("username")
    args = parser.parse_args()
    if args.command == "list-unowned-projects":
        engine = build_engine(get_settings())
        try:
            with Session(engine) as session:
                for slug, name in session.execute(
                    select(Project.slug, Project.name)
                    .where(Project.owner_id.is_(None))
                    .order_by(Project.slug)
                ):
                    print(f"{slug}	{name!r}")
        finally:
            engine.dispose()
        return
    try:
        username = normalize_username(args.username)
        hashed = None
        if args.command == "reset-password":
            if not sys.stdin.isatty():
                raise ValueError("Use an interactive terminal to reset a password.")
            password = getpass("New password: ")
            validate_password(password)
            if password != getpass("Confirm new password: "):
                raise ValueError("Passwords must match.")
            hashed = password_hash(password)
        engine = build_engine(get_settings())
        try:
            with Session(engine) as session, session.begin():
                account = session.scalar(
                    select(Account)
                    .where(Account.username == username)
                    .with_for_update()
                )
                if account is None:
                    raise ValueError("Account not found.")
                if hashed is not None:
                    account.password_hash = hashed
                    session.execute(
                        delete(AccountSession).where(
                            AccountSession.account_id == account.id
                        )
                    )
                else:
                    project = session.scalar(
                        select(Project)
                        .where(Project.slug == args.slug)
                        .with_for_update()
                    )
                    if project is None:
                        raise ValueError("Project not found.")
                    if project.owner_id is not None and project.owner_id != account.id:
                        raise ValueError("Project already has another owner.")
                    project.owner_id = account.id
        finally:
            engine.dispose()
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
    print("Account operation completed.")


if __name__ == "__main__":
    main()
