"""persist browser workspace state

Revision ID: c91e4b4aa210
Revises: e4a91f0b2c77
Create Date: 2026-10-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91e4b4aa210"
down_revision: str | Sequence[str] | None = "e4a91f0b2c77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")
_BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "workspace_states",
        sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
        sa.Column("user_id", _BIGINT, nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "namespace", name="uq_workspace_states_user_namespace"),
    )
    op.create_index("ix_workspace_states_user_id", "workspace_states", ["user_id"])
    op.create_index(
        "ix_workspace_states_user_namespace",
        "workspace_states",
        ["user_id", "namespace"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_states_user_namespace", table_name="workspace_states")
    op.drop_index("ix_workspace_states_user_id", table_name="workspace_states")
    op.drop_table("workspace_states")
