"""add quota reservations

Revision ID: d19b5a2f3b91
Revises: lots_partnerships_001
Create Date: 2026-09-20 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d19b5a2f3b91"
down_revision: Union[str, Sequence[str], None] = "lots_partnerships_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quota_reservations",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reservation_key", sa.String(length=64), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("month_key", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="reserved"),
        sa.Column("reserved_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("release_reason", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quota_reservations_user_id"), "quota_reservations", ["user_id"], unique=False)
    op.create_index("ix_quota_reservations_reservation_key", "quota_reservations", ["reservation_key"], unique=True)
    op.create_index("ix_quota_reservations_operation_key", "quota_reservations", ["operation_key"], unique=False)
    op.create_index("ix_quota_reservations_month_key", "quota_reservations", ["month_key"], unique=False)
    op.create_index("ix_quota_reservations_status", "quota_reservations", ["status"], unique=False)
    op.create_index("ix_quota_reservations_reserved_at", "quota_reservations", ["reserved_at"], unique=False)
    op.create_index("ix_quota_reservations_expires_at", "quota_reservations", ["expires_at"], unique=False)
    op.create_index(
        "ix_quota_reservations_user_month_status",
        "quota_reservations",
        ["user_id", "month_key", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quota_reservations_user_month_status", table_name="quota_reservations")
    op.drop_index("ix_quota_reservations_expires_at", table_name="quota_reservations")
    op.drop_index("ix_quota_reservations_reserved_at", table_name="quota_reservations")
    op.drop_index("ix_quota_reservations_status", table_name="quota_reservations")
    op.drop_index("ix_quota_reservations_month_key", table_name="quota_reservations")
    op.drop_index("ix_quota_reservations_operation_key", table_name="quota_reservations")
    op.drop_index("ix_quota_reservations_reservation_key", table_name="quota_reservations")
    op.drop_index(op.f("ix_quota_reservations_user_id"), table_name="quota_reservations")
    op.drop_table("quota_reservations")
