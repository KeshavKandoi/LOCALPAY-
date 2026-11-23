import sqlalchemy as sa

from alembic import op

revision = "0010_payment_chaos"
down_revision = "0009_chaos_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("simulation_key", sa.String(128)))
    op.add_column("payments", sa.Column("simulation_outcome", sa.String(40)))
    op.create_unique_constraint(
        op.f("uq_payments_project_id_simulation_key"),
        "payments",
        ["project_id", "simulation_key"],
    )
    op.drop_constraint(
        op.f("ck_scenario_executions_status"), "scenario_executions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_scenario_executions_status"),
        "scenario_executions",
        "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
    )
    op.create_table(
        "gateway_faults",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("remaining", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_gateway_faults")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_gateway_faults_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "execution_id"],
            ["scenario_executions.project_id", "scenario_executions.id"],
            name=op.f("fk_gateway_faults_project_id_execution_id_scenario_executions"),
        ),
        sa.CheckConstraint(
            "status_code IN (429, 503)", name=op.f("ck_gateway_faults_status_code")
        ),
        sa.CheckConstraint(
            "remaining BETWEEN 0 AND 10", name=op.f("ck_gateway_faults_remaining")
        ),
    )


def downgrade() -> None:
    op.drop_table("gateway_faults")
    op.execute(
        "UPDATE scenario_executions SET status = 'failed' WHERE status = 'cancelled'"
    )
    op.drop_constraint(
        op.f("ck_scenario_executions_status"), "scenario_executions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_scenario_executions_status"),
        "scenario_executions",
        "status IN ('pending', 'running', 'succeeded', 'failed')",
    )
    op.drop_constraint(
        op.f("uq_payments_project_id_simulation_key"), "payments", type_="unique"
    )
    op.drop_column("payments", "simulation_outcome")
    op.drop_column("payments", "simulation_key")
