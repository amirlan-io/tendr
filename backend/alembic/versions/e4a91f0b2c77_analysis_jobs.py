"""persisted analysis jobs

Revision ID: e4a91f0b2c77
Revises: a7c31e9d5b21
Create Date: 2026-10-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a91f0b2c77"
down_revision: Union[str, Sequence[str], None] = "a7c31e9d5b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")
_BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", _BIGINT, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=160), nullable=False, server_default="Задание создано"),
        sa.Column("input_json", _JSON, nullable=False),
        sa.Column("result_json", _JSON, nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("analysis_id", _BIGINT, nullable=True),
        sa.Column("reservation_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    op.create_index("ix_analysis_jobs_user_id", "analysis_jobs", ["user_id"])
    op.create_index("ix_analysis_jobs_analysis_id", "analysis_jobs", ["analysis_id"])
    op.create_index("ix_analysis_jobs_created_at", "analysis_jobs", ["created_at"])
    op.create_index("ix_analysis_jobs_user_created", "analysis_jobs", ["user_id", "created_at"])
    op.create_index("ix_analysis_jobs_user_status", "analysis_jobs", ["user_id", "status"])


def downgrade() -> None:
    op.drop_table("analysis_jobs")
