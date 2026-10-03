from __future__ import annotations

import pytest

from app.agents.legal import LegalAgent
from app.api import health as health_module
from app.core.config import Settings


class _EmptyRAG:
    def count(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_legal_agent_refuses_empty_rag_without_llm_call(monkeypatch):
    legal = LegalAgent(rag=_EmptyRAG())
    called = False

    async def _raise_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("LLM should not run when the legal RAG is empty")

    monkeypatch.setattr(legal, "_chat_json", _raise_if_called)

    result = await legal.run("Нужно проверить закупку", lot_id="LOT-EMPTY")

    assert called is False
    assert result.overall_risk == "needs_review"
    assert result.items == []
    assert result.checks == []
    assert result.complaint_draft is None
    assert "RAG" in result.summary


@pytest.mark.asyncio
async def test_health_checks_report_degraded_when_qdrant_unavailable(monkeypatch):
    settings = Settings(app_name="tendr", app_env="dev", llm_provider="mistral")

    async def _fake_ping():
        raise RuntimeError("db down")

    monkeypatch.setattr(health_module, "_db_ping", _fake_ping)
    monkeypatch.setattr(health_module, "_qdrant_is_available", lambda: False)

    result = await health_module.health(settings)

    assert result["status"] == "degraded"
    assert "db" in result["checks"]["database"].lower()
    assert "qdrant" in result["checks"]["qdrant"].lower()
