from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import lots as lots_api


@pytest.mark.asyncio
async def test_assistant_chat_is_grounded_in_owned_completed_job(monkeypatch) -> None:
    job = SimpleNamespace(
        id="a" * 32,
        user_id=7,
        status="completed",
        input_json={"url": "https://goszakup.gov.kz/ru/announce/show/12345"},
        result_json={
            "lot": {
                "lot_id": "12345",
                "title": "Поставка фильтров",
                "customer": "ГУ Заказчик",
                "requirements": [{"title": "Сертификат", "is_mandatory": True}],
            },
            "legal": {"overall_risk": "medium"},
        },
    )

    async def get_user(_db, _client_id):
        return SimpleNamespace(id=7)

    class QueryResult:
        @staticmethod
        def scalar_one_or_none():
            return job

    class FakeDb:
        async def execute(self, _query):
            return QueryResult()

    captured = {}

    class FakeLlm:
        async def chat(self, messages, **_kwargs):
            captured["messages"] = messages
            return SimpleNamespace(content="Нужен обязательный сертификат.")

    monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", get_user)
    monkeypatch.setattr(lots_api, "get_llm", lambda: FakeLlm())
    response = await lots_api.chat_with_tender_assistant(
        payload=lots_api.AssistantChatRequest(
            message="Что от меня требуется?",
            job_id=job.id,
            history=[],
        ),
        client_id="web_1234567890abcd",
        db=FakeDb(),
    )

    assert response["grounded"] is True
    assert response["lot_id"] == "12345"
    assert response["answer"] == "Нужен обязательный сертификат."
    assert "Поставка фильтров" in captured["messages"][0].content
    assert "Никогда не придумывай" in captured["messages"][0].content


def test_assistant_context_is_bounded_and_marks_missing_context() -> None:
    empty_context, lot_id = lots_api._assistant_context(None)
    assert "не загружен" in empty_context
    assert lot_id is None

    huge_job = SimpleNamespace(
        input_json={"filename": "spec.pdf"},
        result_json={
            "lot": {
                "lot_id": "1",
                "technical_specification": "x" * 60_000,
                "requirements": [{"title": "Лицензия обязательна"}],
            }
        },
    )
    context, lot_id = lots_api._assistant_context(huge_job)
    assert len(context) <= 45_000
    assert lot_id == "1"
    assert "Лицензия обязательна" in context
