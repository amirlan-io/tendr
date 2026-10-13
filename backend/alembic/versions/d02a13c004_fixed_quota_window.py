"""Replace monthly quotas with persistent five-hour windows; preserve the ledger."""

from alembic import op
import sqlalchemy as sa

revision = "d02a13c004"
down_revision = "d02a13c003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("quota_window_started_at", sa.DateTime(), nullable=True))
    op.add_column(
        "quota_reservations", sa.Column("window_started_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "ix_quota_reservations_user_window_status",
        "quota_reservations",
        ["user_id", "window_started_at", "status"],
    )


def downgrade():
    op.drop_index("ix_quota_reservations_user_window_status", table_name="quota_reservations")
    op.drop_column("quota_reservations", "window_started_at")
    op.drop_column("users", "quota_window_started_at")
