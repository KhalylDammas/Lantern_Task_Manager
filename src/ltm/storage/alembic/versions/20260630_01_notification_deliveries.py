"""Add notification delivery log table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260630_01"
down_revision = "20260629_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ltm_notification_deliveries" in inspect(bind).get_table_names():
        return
    op.create_table(
        "ltm_notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("event", sa.String(length=48), nullable=False),
        sa.Column("recipient_entra_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("activity_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bot_dm_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("needs_retry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ltm_notification_deliveries_idempotency_key",
        "ltm_notification_deliveries",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_ltm_notification_deliveries_recipient_entra_id",
        "ltm_notification_deliveries",
        ["recipient_entra_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "ltm_notification_deliveries" not in inspect(bind).get_table_names():
        return
    op.drop_table("ltm_notification_deliveries")
