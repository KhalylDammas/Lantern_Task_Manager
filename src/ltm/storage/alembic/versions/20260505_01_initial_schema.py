"""Initial LTM tables (tasks, counters, audit JSON, idempotency, Teams bindings).

Revision ID: 20260505_01
Revises:
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltm_task_counters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("department_code", sa.String(length=8), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("department_code", "year", name="uq_counter_dept_year"),
    )
    op.create_table(
        "ltm_tasks",
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=200), nullable=False),
        sa.Column("department_display", sa.String(length=120), nullable=False),
        sa.Column("department_code", sa.String(length=8), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=24), nullable=False),
        sa.Column("created_by_entra_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("created_by_department", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("assigned_to_entra_id", sa.String(length=64), nullable=False),
        sa.Column("assigned_to_display_name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("assigned_to_department", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closure_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_overdue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("escalation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("d365_references", sa.JSON(), nullable=False),
        sa.Column("audit_trail", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_ltm_tasks_created_by_entra_id", "ltm_tasks", ["created_by_entra_id"], unique=False)
    op.create_index("ix_ltm_tasks_assigned_to_entra_id", "ltm_tasks", ["assigned_to_entra_id"], unique=False)
    op.create_index("ix_ltm_tasks_status", "ltm_tasks", ["status"], unique=False)
    op.create_table(
        "ltm_idempotency",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "ltm_conversation_bindings",
        sa.Column("user_entra_id", sa.String(length=64), nullable=False),
        sa.Column("ref_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_entra_id"),
    )


def downgrade() -> None:
    op.drop_table("ltm_conversation_bindings")
    op.drop_table("ltm_idempotency")
    op.drop_index("ix_ltm_tasks_status", table_name="ltm_tasks")
    op.drop_index("ix_ltm_tasks_assigned_to_entra_id", table_name="ltm_tasks")
    op.drop_index("ix_ltm_tasks_created_by_entra_id", table_name="ltm_tasks")
    op.drop_table("ltm_tasks")
    op.drop_table("ltm_task_counters")
