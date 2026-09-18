"""add lots and partnerships

Revision ID: lots_partnerships_001
Revises: 72ce691e76ec
Create Date: 2026-07-07 22:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'lots_partnerships_001'
down_revision: Union[str, None] = '72ce691e76ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lots',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('source_id', sa.String(length=128), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=64), nullable=True),
        sa.Column('procurement_method', sa.String(length=128), nullable=True),
        sa.Column('platform', sa.String(length=128), nullable=True),
        sa.Column('amount_kzt', sa.Float(), nullable=True),
        sa.Column('price_per_unit', sa.Float(), nullable=True),
        sa.Column('region', sa.String(length=128), nullable=True),
        sa.Column('delivery_address', sa.Text(), nullable=True),
        sa.Column('publish_date', sa.DateTime(), nullable=True),
        sa.Column('deadline_date', sa.DateTime(), nullable=True),
        sa.Column('organizer', sa.String(length=512), nullable=True),
        sa.Column('organizer_bin', sa.String(length=32), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='published'),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_red_flags', sa.Text(), nullable=True),
        sa.Column('ai_match_score', sa.Integer(), nullable=True),
        sa.Column('ai_processed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('raw_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_lots_source', 'lots', ['source'])
    op.create_index('ix_lots_source_id', 'lots', ['source_id'])
    op.create_index('ix_lots_category', 'lots', ['category'])
    op.create_index('ix_lots_procurement_method', 'lots', ['procurement_method'])
    op.create_index('ix_lots_platform', 'lots', ['platform'])
    op.create_index('ix_lots_amount_kzt', 'lots', ['amount_kzt'])
    op.create_index('ix_lots_region', 'lots', ['region'])
    op.create_index('ix_lots_publish_date', 'lots', ['publish_date'])
    op.create_index('ix_lots_deadline_date', 'lots', ['deadline_date'])
    op.create_index('ix_lots_status', 'lots', ['status'])
    op.create_unique_constraint('uq_lot_source_id', 'lots', ['source', 'source_id'])
    op.create_index('ix_lots_status_deadline', 'lots', ['status', 'deadline_date'])
    op.create_index('ix_lots_platform_region', 'lots', ['platform', 'region'])

    op.create_table(
        'lot_partnerships',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('lot_id', sa.BigInteger(), sa.ForeignKey('lots.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('contact', sa.String(length=256), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_lot_partnerships_lot_id', 'lot_partnerships', ['lot_id'])
    op.create_index('ix_lot_partnerships_user_id', 'lot_partnerships', ['user_id'])
    op.create_unique_constraint('uq_lot_user_role', 'lot_partnerships', ['lot_id', 'user_id', 'role'])


def downgrade() -> None:
    op.drop_table('lot_partnerships')
    op.drop_table('lots')
