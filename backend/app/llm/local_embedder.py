"""Локальный эмбеддер на sentence-transformers.

Используется как fallback, когда LLM-провайдер (alemLLM, Mistral) не
поддерживает эмбеддинги. Лёгкая модель, работает на CPU, без GPU.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.llm.base import EmbeddingResponse, LLMProvider, LLMResponse, Message


class LocalEmbedder:
    """Эмбеддер через sentence-transformers. Только embed/embed_batch, без chat.

    Имеет тот же интерфейс для эмбеддингов, что и LLMProvider, чтобы RAG
    мог его использовать.
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'Local embeddings are not installed. Run: pip install -e ".[local-embeddings]"'
            ) from exc

        logger.info("Loading local embedder model: {}", model_name)
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        # multilingual-e5-* требует префикс "query: " / "passage: " для лучшего качества
        self._prefix = "passage: " if "e5" in model_name.lower() else ""
        self._query_prefix = "query: " if "e5" in model_name.lower() else ""
        logger.info(
            "Local embedder ready: dim={}, device={}",
            self._model.get_embedding_dimension(),
            self._model.device,
        )

    @property
    def name(self) -> str:
        return f"local:{self._model_name}"

    @property
    def dim(self) -> int:
        return self._model.get_embedding_dimension()

    def _maybe_prefix(self, text: str, is_query: bool = False) -> str:
        if not self._prefix:
            return text
        prefix = self._query_prefix if is_query else self._prefix
        return prefix + text

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def embed(self, text: str, *, is_query: bool = False) -> EmbeddingResponse:
        vec = self._model.encode(self._maybe_prefix(text, is_query), convert_to_numpy=True)
        return EmbeddingResponse(vector=vec.tolist(), model=self._model_name)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def embed_batch(self, texts: list[str], *, is_query: bool = False) -> list[EmbeddingResponse]:
        prefixed = [self._maybe_prefix(t, is_query) for t in texts]
        vecs = self._model.encode(prefixed, convert_to_numpy=True, show_progress_bar=False)
        return [EmbeddingResponse(vector=v.tolist(), model=self._model_name) for v in vecs]


# Singleton
_local_embedder: LocalEmbedder | None = None


def get_local_embedder() -> LocalEmbedder:
    global _local_embedder
    if _local_embedder is None:
        _local_embedder = LocalEmbedder()
    return _local_embedder
