"""Lease ownership and bounded recovery of analysis jobs."""
from alembic import op
import sqlalchemy as sa
revision = "d02a13c002"
down_revision = "d02a13c001"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("analysis_jobs", sa.Column("lease_owner", sa.String(32), nullable=True))
    op.add_column("analysis_jobs", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.create_index("ix_analysis_jobs_lease_until", "analysis_jobs", ["lease_until"])

def downgrade():
    op.drop_index("ix_analysis_jobs_lease_until", "analysis_jobs")
    for name in ["attempts", "lease_until", "lease_owner"]: op.drop_column("analysis_jobs", name)
