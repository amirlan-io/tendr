"""Non-destructive quota adjustments with an audit trail."""
from alembic import op
import sqlalchemy as sa
revision = "d02a13c003"
down_revision = "d02a13c002"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("quota_reset_at", sa.DateTime(), nullable=True))
    op.create_table("quota_reset_audit",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False))
    op.create_index("ix_quota_reset_audit_user_id", "quota_reset_audit", ["user_id"])

def downgrade():
    op.drop_table("quota_reset_audit")
    op.drop_column("users", "quota_reset_at")
