"""Archive fixes integrated without replacing the current production architecture."""
from types import SimpleNamespace
from datetime import date, timedelta
from unittest.mock import AsyncMock
import socket
import io

import pytest
from docx import Document
from openpyxl import Workbook
from qdrant_client import QdrantClient, models

from app.agents.page_fetcher import is_public_http_url
from app.core.config import get_settings
from app.llm.base import EmbeddingResponse, LLMResponse, Message
from app.llm.failover import FailoverProvider
from app.rag.chunker import Chunk
from app.rag.store import RAGStore
from app.schemas.lot import LotCreate
from app.services.document_reader import DocumentReadError, extract_text
from app.services.orchestrator import LotOrchestrator, QuotaExceeded, analyze_uploaded_file
from app.agents.legal import LegalAgent
from app.rag.store import SearchHit
from app.agents.documenter import DocumenterAgent
from app.services.doc_generator import generate_report_docx


@pytest.mark.asyncio
async def test_failover_retries_recovered_primary_after_cooldown():
    primary = SimpleNamespace(name="primary", chat=AsyncMock(side_effect=RuntimeError("down")))
    secondary = SimpleNamespace(name="secondary", chat=AsyncMock(return_value=LLMResponse("fallback", "fake")))
    provider = FailoverProvider(primary, secondary)
    messages = [Message("user", "test")]
    for _ in range(4):
        assert (await provider.chat(messages)).content == "fallback"
    assert primary.chat.await_count == 3
    primary.chat.side_effect = None
    primary.chat.return_value = LLMResponse("recovered", "fake")
    provider._last_failover_at -= provider._cooldown_seconds + 1
    assert (await provider.chat(messages)).content == "recovered"
    assert (await provider.chat(messages)).content == "recovered"
    assert secondary.chat.await_count == 4


class _Embedder:
    dim = 2

    def embed_batch(self, texts):
        return [EmbeddingResponse([1.0, 0.0], "local") for _ in texts]

    def embed(self, text, *, is_query=False):
        assert is_query, "Search must use the query embedding path"
        return EmbeddingResponse([1.0, 0.0], "local")


@pytest.mark.asyncio
async def test_reindex_is_idempotent_and_search_uses_query_embeddings(monkeypatch):
    client = QdrantClient(location=":memory:")
    monkeypatch.setattr(RAGStore, "_get_client", lambda self: client)
    monkeypatch.setattr(RAGStore, "_get_embedder", lambda self: _Embedder())
    chunks = [Chunk("Текст закона", "law.txt", "law::0001", {})]
    try:
        assert await RAGStore("test_law").upsert(chunks) == 1
        assert await RAGStore("test_law").upsert(chunks) == 1
        assert client.count("test_law", exact=True).count == 1
        hits = await RAGStore("test_law").search("закупки", top_k=1)
        assert hits[0].chunk.text == "Текст закона"
    finally:
        client.close()


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_preserves_existing_collection(monkeypatch):
    client = QdrantClient(location=":memory:")
    client.create_collection("wrong_dim", vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
    monkeypatch.setattr(RAGStore, "_get_client", lambda self: client)
    monkeypatch.setattr(RAGStore, "_get_embedder", lambda self: _Embedder())
    try:
        assert await RAGStore("wrong_dim").upsert([Chunk("text", "law", "1", {})]) == 0
        assert client.get_collection("wrong_dim").config.params.vectors.size == 3
        assert client.count("wrong_dim", exact=True).count == 0
    finally:
        client.close()


@pytest.mark.asyncio
async def test_real_docx_and_xlsx_are_read(tmp_path):
    doc = Document()
    doc.add_paragraph("Поставка 12 металлических стульев")
    doc.save(tmp_path / "spec.docx")
    workbook = Workbook()
    workbook.active.append(["Стулья", 12])
    workbook.save(tmp_path / "spec.xlsx")
    workbook.close()
    assert "12 металлических стульев" in await extract_text(tmp_path / "spec.docx")
    assert "Стулья | 12" in await extract_text(tmp_path / "spec.xlsx")


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content", [("broken.pdf", b"not a pdf"), ("empty.txt", b"")])
async def test_unreadable_documents_raise_instead_of_becoming_analysis(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_bytes(content)
    with pytest.raises(DocumentReadError):
        await extract_text(path, include_vision=False)


@pytest.mark.asyncio
async def test_document_size_limit_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_analysis_chars", 5)
    path = tmp_path / "large.txt"
    path.write_text("too much text")
    with pytest.raises(DocumentReadError, match="слишком большой"):
        await extract_text(path)


@pytest.mark.asyncio
async def test_each_uploaded_document_has_its_own_identity(tmp_path, monkeypatch):
    from app.services import orchestrator

    path = tmp_path / "spec.txt"
    path.write_text("Техническая спецификация")
    captured = []

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            pass

        async def analyze_lot(self, lot, **kwargs):
            captured.append(lot)
            return "result"

    monkeypatch.setattr(orchestrator, "LotOrchestrator", FakeOrchestrator)
    for _ in range(2):
        assert await analyze_uploaded_file(str(path), user_id=1, is_pilot=False, used_this_month=1, free_limit=3) == "result"
    assert captured[0].source_id != captured[1].source_id
    assert all(lot.source_id.startswith("uploaded-") for lot in captured)


@pytest.mark.asyncio
async def test_last_reserved_slot_reaches_analysis_but_next_is_rejected(monkeypatch):
    instance = LotOrchestrator.__new__(LotOrchestrator)
    resolve = AsyncMock(side_effect=RuntimeError("reached parser"))
    monkeypatch.setattr(instance, "_resolve_lot", resolve)
    lot = LotCreate(source_id="123")
    with pytest.raises(RuntimeError, match="reached parser"):
        await instance.analyze_lot(lot, user_id=1, is_pilot=False, used_this_month=3, free_limit=3)
    with pytest.raises(QuotaExceeded):
        await instance.analyze_lot(lot, user_id=1, is_pilot=False, used_this_month=4, free_limit=3)
    assert resolve.await_count == 1


@pytest.mark.parametrize("addresses", [[], ["10.0.0.1"], ["93.184.216.34", "127.0.0.1"]])
def test_dns_guard_rejects_empty_private_or_mixed_answers(monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
    ])
    assert not is_public_http_url("https://public.example/page")


def test_dns_failure_does_not_bypass_ssrf_guard(monkeypatch):
    def unavailable(*args):
        raise socket.gaierror("DNS unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    assert not is_public_http_url("https://public.example/page")


@pytest.mark.asyncio
@pytest.mark.parametrize("verified,review_date", [
    (False, date.today().isoformat()),
    (True, (date.today() - timedelta(days=100)).isoformat()),
    (True, "invalid"),
    (True, (date.today() + timedelta(days=1)).isoformat()),
])
async def test_legal_agent_does_not_use_unverified_or_expired_corpus(monkeypatch, verified, review_date):
    settings = get_settings()
    monkeypatch.setattr(settings, "legal_corpus_verified", verified)
    monkeypatch.setattr(settings, "legal_corpus_reviewed_at", review_date)
    monkeypatch.setattr(settings, "legal_corpus_max_age_days", 90)
    rag = SimpleNamespace(count=lambda: 1, search=AsyncMock())
    agent = LegalAgent(rag)
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(side_effect=AssertionError("Must not call LLM")))
    result = await agent.run("Техническое задание", lot_id="1")
    assert result.overall_risk == "needs_review"
    assert not result.items
    rag.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_legal_citations_must_match_verified_source_and_revision(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "legal_corpus_verified", True)
    monkeypatch.setattr(settings, "legal_corpus_reviewed_at", date.today().isoformat())
    chunk = Chunk("Статья 5. Требования должны быть обоснованы.", "law.txt", "1", {
        "official_url": "https://adilet.zan.kz/test", "version": "2026-10-01", "verified": True,
    })
    rag = SimpleNamespace(count=lambda: 1, search=AsyncMock(return_value=[SearchHit(chunk, 1.0)]))
    agent = LegalAgent(rag)
    rows = [
        {"title": "Подтверждённый пункт", "quote": "Требования должны быть обоснованы.",
         "citation_url": "https://adilet.zan.kz/test", "legal_text_revision": "invented"},
        {"title": "Вымышленная цитата", "quote": "Запрещены все закупки",
         "citation_url": "https://adilet.zan.kz/test"},
        {"title": "Чужой источник", "quote": "Требования должны быть обоснованы.",
         "citation_url": "https://evil.example/test"},
    ]
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(return_value={"items": rows, "overall_risk": "low"}))
    result = await agent.run("Техническое задание", lot_id="1")
    assert [item.title for item in result.items] == ["Подтверждённый пункт"]
    assert result.items[0].legal_text_revision == "2026-10-01"
    assert result.items[0].source == "law.txt"
    assert result.overall_risk == "needs_review"
    assert result.complaint_draft is None


@pytest.mark.asyncio
async def test_overlapping_sections_keep_quantity_and_deduplicate_same_requirement(monkeypatch):
    agent = DocumenterAgent()
    calls = []
    quote = "Стул металлический — 2 шт."
    text = "Начало " + "x" * 9700 + quote + "y" * 700

    async def extract(prompt, **kwargs):
        calls.append(prompt)
        return {"title": "Стулья", "requirements": [{
            "name": "Стул", "value": "Металлический", "quantity": 2, "unit": "шт.",
            "source_quote": quote, "category": "goods", "source_document": "spec.txt",
        }]}

    monkeypatch.setattr(agent, "_chat_json", extract)
    result = await agent.run(text, lot_id="1")
    assert len(calls) == 2
    assert all(quote in call for call in calls)
    assert len(result.requirements) == 1
    requirement = result.requirements[0]
    assert requirement.quantity == 2
    assert requirement.source_document == "spec.txt"
    assert requirement.source_section == "Раздел 1"
    assert requirement.source_quote == quote


def test_docx_report_contains_requirement_value_quote_and_section():
    report = generate_report_docx({"title": "Стулья", "requirements": [{
        "name": "Стул", "value": "Металлический", "source_quote": "Поставка двух стульев",
        "source_section": "Раздел 2",
    }]}, None)
    paragraphs = "\n".join(p.text for p in Document(io.BytesIO(report)).paragraphs)
    assert "Стул: Металлический" in paragraphs
    assert "Поставка двух стульев" in paragraphs
    assert "Раздел 2" in paragraphs


@pytest.mark.asyncio
async def test_oversized_spreadsheet_is_rejected_instead_of_silently_truncated(tmp_path, monkeypatch):
    from app.services import document_reader

    monkeypatch.setattr(document_reader, "MAX_EXCEL_ROWS", 2)
    workbook = Workbook()
    for number in range(3):
        workbook.active.append(["Товар", number])
    path = tmp_path / "large.xlsx"
    workbook.save(path)
    workbook.close()
    with pytest.raises(DocumentReadError, match="лимит"):
        await extract_text(path)
