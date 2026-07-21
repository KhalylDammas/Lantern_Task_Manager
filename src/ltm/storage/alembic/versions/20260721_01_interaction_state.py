"""Durable interaction sessions and task drafts."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_01"
down_revision = "20260630_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltm_interaction_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_entra_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(256), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_operation", sa.String(32), nullable=False, server_default=""),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("reference_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_activity_id", sa.String(256), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_entra_id", "conversation_id", name="uq_interaction_actor_conversation"),
    )
    op.create_index("ix_interaction_actor", "ltm_interaction_sessions", ["actor_entra_id"])
    op.create_index("ix_interaction_conversation", "ltm_interaction_sessions", ["conversation_id"])
    op.create_table(
        "ltm_task_drafts",
        sa.Column("draft_id", sa.String(32), primary_key=True),
        sa.Column("requester_entra_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_drafts_requester", "ltm_task_drafts", ["requester_entra_id"])


def downgrade() -> None:
    op.drop_index("ix_task_drafts_requester", table_name="ltm_task_drafts")
    op.drop_table("ltm_task_drafts")
    op.drop_index("ix_interaction_conversation", table_name="ltm_interaction_sessions")
    op.drop_index("ix_interaction_actor", table_name="ltm_interaction_sessions")
    op.drop_table("ltm_interaction_sessions")
