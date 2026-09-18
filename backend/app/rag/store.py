"""Обёртка над Qdrant: создание коллекции, индексация, поиск.

Lazy-init: Qdrant-клиент создаётся при первом обращении, а не в __init__.
Если Qdrant недоступен, методы возвращают пустые результаты вместо падения.

Важная особенность: в локальном режиме (QdrantClient(path=...)) только один
клиент может держать папку открытой. Поэтому используем общий singleton-клиент
для всех RAGStore-инстансов — иначе Legal и B2G агенты падают с ошибкой
"Storage folder is already accessed by another instance".
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Sequence

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import get_settings
from app.llm import get_llm
from app.llm.local_embedder import LocalEmbedder, get_local_embedder
from app.rag.chunker import Chunk


# Singleton Qdrant-клиент — общий для всех RAGStore.
# В локальном режиме (QdrantClient(path=...)) только один клиент может
# открывать storage folder; без singleton Legal/B2G агенты падают.
_shared_client: QdrantClient | None = None
_shared_client_lock = threading.Lock()
_shared_client_path: str | None = None  # для инвалидации при смене path


def _get_shared_qdrant_client() -> QdrantClient | None:
    """Возвращает общий QdrantClient. Singleton по path.

    Для удалённого режима (QdrantClient(url=...)) тоже используем общий
    клиент — это и производительно, и не создаёт лишних коннектов.
    """
    global _shared_client, _shared_client_path
    with _shared_client_lock:
        if _shared_client is not None:
            return _shared_client
        try:
            s = get_settings()
            url = (s.qdrant_url or "").strip()
            if url.startswith("local://"):
                path = url[len("local://"):]
                logger.info("RAGStore: using local Qdrant at path='{}'", path)
                _shared_client = QdrantClient(path=path)
                _shared_client_path = path
            elif url:
                _shared_client = QdrantClient(url=url, api_key=s.qdrant_api_key or None)
                _shared_client_path = url
            else:
                logger.warning("QDRANT_URL is empty, RAG disabled")
                return None
        except Exception as e:
            logger.warning("Qdrant client init failed: {}", e)
            return None
        return _shared_client


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


class RAGStore:
    """Тонкая обёртка над Qdrant. Одна коллекция = один домен."""

    def __init__(self, collection: str) -> None:
        self.collection = collection
        self._ensured = False
        self._llm = None
        self._embedder: LocalEmbedder | None = None

    def _get_client(self) -> QdrantClient | None:
        # Используем общий singleton-клиент
        return _get_shared_qdrant_client()

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_llm()
        return self._llm

    def _get_embedder(self):
        """Возвращает эмбеддер. Может быть sync (Local) или async (LLM).

        RAGStore.upsert/search проверяют тип и вызывают соответственно.
        """
        s = get_settings()
        if s.embedding_provider == "llm":
            return self._get_llm()  # async
        if self._embedder is None:
            self._embedder = get_local_embedder()
        return self._embedder  # sync

    def _ensure_collection(self) -> bool:
        if self._ensured:
            return True
        client = self._get_client()
        if client is None:
            return False
        try:
            existing = {c.name for c in client.get_collections().collections}
            if self.collection in existing:
                # Если существующая коллекция имеет другой dim — несовместимо.
                # Логируем и используем её как есть.
                info = client.get_collection(self.collection)
                actual_dim = info.config.params.vectors.size
                logger.info(
                    "Qdrant collection '{}' already exists (dim={})",
                    self.collection,
                    actual_dim,
                )
                self._ensured = True
                return True
            # dim берём из реального эмбеддера
            emb = self._get_embedder()
            if hasattr(emb, "dim"):
                dim = emb.dim
            else:
                dim = get_settings().embedding_dim
            client.create_collection(
                collection_name=self.collection,
                vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
            )
            logger.info("Qdrant collection '{}' created (dim={})", self.collection, dim)
            self._ensured = True
            return True
        except Exception as e:
            logger.warning("Failed to ensure Qdrant collection {}: {}", self.collection, e)
            return False

    async def upsert(self, chunks: Sequence[Chunk]) -> int:
        if not chunks:
            return 0
        if not self._ensure_collection():
            logger.warning("RAG upsert skipped: Qdrant unavailable")
            return 0
        client = self._get_client()
        if client is None:
            return 0
        emb = self._get_embedder()
        try:
            texts = [c.text for c in chunks]
            # Локальный эмбеддер синхронный, LLM — асинхронный
            import inspect

            if inspect.iscoroutinefunction(emb.embed_batch):
                embs = await emb.embed_batch(texts)
            else:
                embs = emb.embed_batch(texts)
        except Exception as e:
            logger.error("Embedding failed during upsert: {}", e)
            return 0
        points: list[qmodels.PointStruct] = []
        for chunk, e in zip(chunks, embs):
            points.append(
                qmodels.PointStruct(
                    id=hash(chunk.chunk_id) & 0x7FFFFFFF,
                    vector=e.vector,
                    payload={
                        "text": chunk.text,
                        "source": chunk.source,
                        "chunk_id": chunk.chunk_id,
                        **chunk.metadata,
                    },
                )
            )
        try:
            client.upsert(collection_name=self.collection, points=points, wait=True)
        except Exception as e:
            logger.error("Qdrant upsert failed: {}", e)
            return 0
        return len(points)

    async def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        if not self._ensure_collection():
            return []
        client = self._get_client()
        if client is None:
            return []
        try:
            emb_obj = self._get_embedder()
            import inspect

            if inspect.iscoroutinefunction(emb_obj.embed):
                emb = await emb_obj.embed(query)
            else:
                emb = emb_obj.embed(query)
            # qdrant-client >= 1.10: query_points; < 1.10: search
            if hasattr(client, "query_points"):
                resp = client.query_points(
                    collection_name=self.collection,
                    query=emb.vector,
                    limit=top_k,
                    with_payload=True,
                )
                results = resp.points
            else:
                results = client.search(
                    collection_name=self.collection,
                    query_vector=emb.vector,
                    limit=top_k,
                    with_payload=True,
                )
        except Exception as e:
            logger.warning("Qdrant search failed: {}", e)
            return []
        hits: list[SearchHit] = []
        for r in results:
            payload = r.payload or {}
            chunk = Chunk(
                text=payload.get("text", ""),
                source=payload.get("source", ""),
                chunk_id=payload.get("chunk_id", ""),
                metadata={
                    k: v for k, v in payload.items() if k not in {"text", "source", "chunk_id"}
                },
            )
            hits.append(SearchHit(chunk=chunk, score=float(r.score)))
        return hits

    def count(self) -> int:
        if not self._ensure_collection():
            return 0
        client = self._get_client()
        if client is None:
            return 0
        try:
            # qdrant-client >= 1.10: count возвращает CountResult с .count
            res = client.count(collection_name=self.collection)
            return getattr(res, "count", res) if res is not None else 0
        except Exception:
            return 0

    def close(self) -> None:
        # Не закрываем общий singleton-клиент здесь — он может использоваться
        # другими RAGStore-инстансами. Закрытие управляется через close_all()
        # при остановке приложения.
        pass


def close_all() -> None:
    """Закрыть общий Qdrant-клиент. Вызывать при остановке приложения."""
    global _shared_client
    if _shared_client is not None:
        try:
            _shared_client.close()
        except Exception:
            pass
        _shared_client = None
