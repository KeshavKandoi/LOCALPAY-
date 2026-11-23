import sqlalchemy as sa

from alembic import op

revision = "0012_accounts"
down_revision = "0011_reliability_suites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "username ~ '^[a-z0-9][a-z0-9_-]{2,31}$'",
            name="ck_accounts_username_format",
        ),
    )
    op.create_table(
        "account_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_account_sessions_account_id", "account_sessions", ["account_id"]
    )
    op.create_index(
        "ix_account_sessions_expires_at", "account_sessions", ["expires_at"]
    )
    op.add_column("projects", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_projects_owner_id_accounts", "projects", "accounts", ["owner_id"], ["id"]
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("fk_projects_owner_id_accounts", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
    op.drop_table("account_sessions")
    op.drop_table("accounts")
