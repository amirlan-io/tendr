"""Signed Telegram account linking and legacy outreach reconciliation."""
from alembic import op
import sqlalchemy as sa
revision = "d02a13c001"
down_revision = "c91e4b4aa210"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("telegram_link_tokens",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_telegram_link_tokens_user_id", "telegram_link_tokens", ["user_id"])
    op.execute("UPDATE approval_queue SET status='needs_review' WHERE status='approved' AND EXISTS (SELECT 1 FROM outreach_jobs WHERE outreach_jobs.approval_id=approval_queue.id)")

def downgrade():
    op.drop_table("telegram_link_tokens")
