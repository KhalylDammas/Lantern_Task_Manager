"""Daily LLM usage aggregates for governance (C09).

Revision ID: 20260629_01
Revises: 20260505_01
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260629_01"
down_revision = "20260505_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ltm_llm_usage_daily" in inspect(bind).get_table_names():
        return
    op.create_table(
        "ltm_llm_usage_daily",
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("usage_date", "provider", "model_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "ltm_llm_usage_daily" not in inspect(bind).get_table_names():
        return
    op.drop_table("ltm_llm_usage_daily")
