import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_reliability_suites"
down_revision = "0010_payment_chaos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reliability_suites",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("project_id", "id", name=op.f("pk_reliability_suites")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_reliability_suites_project_id_projects"),
        ),
        sa.UniqueConstraint(
            "project_id", "name", name=op.f("uq_reliability_suites_project_id_name")
        ),
    )
    op.add_column("reliability_test_runs", sa.Column("suite_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_reliability_test_runs_project_id_suite_id_reliability_suites"),
        "reliability_test_runs",
        "reliability_suites",
        ["project_id", "suite_id"],
        ["project_id", "id"],
    )
    op.create_index(
        "ix_reliability_runs_status_created_at",
        "reliability_test_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reliability_runs_status_created_at", table_name="reliability_test_runs"
    )
    op.drop_constraint(
        op.f("fk_reliability_test_runs_project_id_suite_id_reliability_suites"),
        "reliability_test_runs",
        type_="foreignkey",
    )
    op.drop_column("reliability_test_runs", "suite_id")
    op.drop_table("reliability_suites")
