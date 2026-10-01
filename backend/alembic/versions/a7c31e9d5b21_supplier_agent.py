"""supplier agent: profiles, candidates, approvals, outreach, personalization

Revision ID: a7c31e9d5b21
Revises: d19b5a2f3b91
Create Date: 2026-09-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c31e9d5b21"
down_revision: Union[str, Sequence[str], None] = "d19b5a2f3b91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB on PostgreSQL, JSON elsewhere (mirrors app.db.models.JSONType)
_JSON = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")
_BIGINT_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
_NOW = sa.text("CURRENT_TIMESTAMP")


def _idx(name: str, table: str, *cols: str, unique: bool = False) -> None:
    op.create_index(name, table, list(cols), unique=unique)


def upgrade() -> None:
    # ── company_profiles (F7) ──
    op.create_table(
        "company_profiles",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("categories", _JSON, nullable=True),
        sa.Column("regions", _JSON, nullable=True),
        sa.Column("budget_min_kzt", sa.Float(), nullable=True),
        sa.Column("budget_max_kzt", sa.Float(), nullable=True),
        sa.Column("min_check_kzt", sa.Float(), nullable=True),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("work_email", sa.String(length=255), nullable=True),
        sa.Column("work_phone", sa.String(length=32), nullable=True),
        sa.Column("contact_name", sa.String(length=128), nullable=True),
        sa.Column("outreach_mode", sa.String(length=16), nullable=False, server_default="review"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_company_profiles_user_id", "company_profiles", "user_id", unique=True)

    # ── supplier_allowlist / supplier_blocklist (F7) ──
    for table, unique_name, has_reason in (
        ("supplier_allowlist", "uq_allowlist_user_supplier", False),
        ("supplier_blocklist", "uq_blocklist_user_supplier", True),
    ):
        columns = [
            sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("supplier", sa.String(length=256), nullable=False),
            sa.Column("domain", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        ]
        if table == "supplier_allowlist":
            columns.insert(4, sa.Column("note", sa.String(length=512), nullable=True))
        else:
            columns.insert(4, sa.Column("reason", sa.String(length=512), nullable=True))
        assert has_reason in (True, False)
        op.create_table(
            table,
            *columns,
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "supplier", name=unique_name),
        )
        _idx(f"ix_{table}_user_id", table, "user_id")
        _idx(f"ix_{table}_supplier", table, "supplier")
        _idx(f"ix_{table}_domain", table, "domain")

    # ── supplier_candidates (F1–F3) ──
    op.create_table(
        "supplier_candidates",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.String(length=64), nullable=False),
        sa.Column("supplier", sa.String(length=256), nullable=False),
        sa.Column("domain", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("card_json", _JSON, nullable=True),
        sa.Column("match_json", _JSON, nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_supplier_candidates_user_id", "supplier_candidates", "user_id")
    _idx("ix_supplier_candidates_lot_id", "supplier_candidates", "lot_id")
    _idx("ix_supplier_candidates_domain", "supplier_candidates", "domain")
    _idx("ix_supplier_candidates_status", "supplier_candidates", "status")
    _idx("ix_supplier_candidates_created_at", "supplier_candidates", "created_at")
    _idx("ix_supplier_candidates_user_lot", "supplier_candidates", "user_id", "lot_id")

    # ── approval_queue (F3–F6) ──
    op.create_table(
        "approval_queue",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("plan_json", _JSON, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.String(length=512), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["supplier_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_approval_queue_user_id", "approval_queue", "user_id")
    _idx("ix_approval_queue_candidate_id", "approval_queue", "candidate_id")
    _idx("ix_approval_queue_kind", "approval_queue", "kind")
    _idx("ix_approval_queue_status", "approval_queue", "status")
    _idx("ix_approval_queue_created_at", "approval_queue", "created_at")

    # ── outreach_jobs (F4–F5) ──
    op.create_table(
        "outreach_jobs",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("approval_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("price_outcome", sa.String(length=24), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("transcription", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_queue.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_outreach_jobs_user_id", "outreach_jobs", "user_id")
    _idx("ix_outreach_jobs_approval_id", "outreach_jobs", "approval_id")
    _idx("ix_outreach_jobs_kind", "outreach_jobs", "kind")
    _idx("ix_outreach_jobs_status", "outreach_jobs", "status")
    _idx("ix_outreach_jobs_created_at", "outreach_jobs", "created_at")

    # ── price_policies (F6) ──
    op.create_table(
        "price_policies",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tolerance_pct", sa.Float(), nullable=False, server_default="5"),
        sa.Column("counter_limit_pct", sa.Float(), nullable=False, server_default="15"),
        sa.Column("counter_script", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_price_policies_user_id", "price_policies", "user_id", unique=True)

    # ── user_interests (F8) ──
    op.create_table(
        "user_interests",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("categories", _JSON, nullable=True),
        sa.Column("regions", _JSON, nullable=True),
        sa.Column("keywords", _JSON, nullable=True),
        sa.Column("min_budget_kzt", sa.Float(), nullable=True),
        sa.Column("max_budget_kzt", sa.Float(), nullable=True),
        sa.Column("quiz_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_user_interests_user_id", "user_interests", "user_id", unique=True)

    # ── tender_feedback (F8) ──
    op.create_table(
        "tender_feedback",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_tender_feedback_user_id", "tender_feedback", "user_id")
    _idx("ix_tender_feedback_lot_id", "tender_feedback", "lot_id")
    _idx("ix_tender_feedback_verdict", "tender_feedback", "verdict")
    _idx("ix_tender_feedback_created_at", "tender_feedback", "created_at")

    # ── digest_settings (F8) ──
    op.create_table(
        "digest_settings",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channels", _JSON, nullable=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("hour_kz", sa.Integer(), nullable=False, server_default="9"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_digest_settings_user_id", "digest_settings", "user_id", unique=True)

    # ── agent_audit_log (F10) ──
    op.create_table(
        "agent_audit_log",
        sa.Column("id", _BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("lot_id", sa.String(length=64), nullable=True),
        sa.Column("target", sa.String(length=256), nullable=True),
        sa.Column("detail_json", _JSON, nullable=True),
        sa.Column("llm_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tavily_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("browser_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("call_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _idx("ix_agent_audit_log_user_id", "agent_audit_log", "user_id")
    _idx("ix_agent_audit_log_action", "agent_audit_log", "action")
    _idx("ix_agent_audit_log_lot_id", "agent_audit_log", "lot_id")
    _idx("ix_agent_audit_log_created_at", "agent_audit_log", "created_at")


def downgrade() -> None:
    for table in (
        "agent_audit_log",
        "digest_settings",
        "tender_feedback",
        "user_interests",
        "price_policies",
        "outreach_jobs",
        "approval_queue",
        "supplier_candidates",
        "supplier_blocklist",
        "supplier_allowlist",
        "company_profiles",
    ):
        op.drop_table(table)