"""Скрипт для индексации нормативной базы в RAG.

Использование:
    python -m app.rag.indexer <путь_к_файлу_или_директории>

Поддерживает .pdf, .docx, .txt, .md. Рекурсивно обходит директории.
Результат: чанки уходят в Qdrant-коллекцию "law_kz".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import hashlib
from qdrant_client import models
from pathlib import Path

from loguru import logger

from app.core.logging import setup_logging
from app.core.config import get_settings
from app.rag import RAGStore, split_into_chunks
from app.services.document_reader import extract_text

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


async def index_path(path: str | Path, collection: str = "law_kz") -> int:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    files = list(p.rglob("*")) if p.is_dir() else [p]
    files = sorted(f for f in files if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES)
    if not files:
        logger.warning("Нет подходящих файлов в {}", p)
        return 0

    manifest_path = (p if p.is_dir() else p.parent) / "corpus.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    all_chunks = []
    for f in files:
        logger.info("Индексирую {}", f)
        text = await extract_text(f)
        chunks = split_into_chunks(
            text,
            source=str(f.relative_to(p.parent if p.is_dir() else p.parent)),
            metadata={"filename": f.name, "kind": "law", **manifest.get(f.name, {})},
        )
        logger.info("  {} чанков, индексирую…", len(chunks))
        all_chunks.extend(chunks)
    if not all_chunks:
        raise RuntimeError("Corpus is empty; active collection is unchanged")
    settings = get_settings()
    fingerprint = [settings.embedding_provider, settings.embedding_dim,
        settings.embedding_local_model, settings.llm_embedding_model]
    digest = hashlib.sha256(json.dumps([fingerprint, [
        {"text": c.text, "source": c.source, "metadata": c.metadata}
        for c in all_chunks
    ]], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    version = f"{collection}_v_{digest}"
    store = RAGStore(collection=version)
    total = await store.upsert(all_chunks)
    if total != len(all_chunks):
        raise RuntimeError("Incomplete corpus index; active collection is unchanged")
    client = store._get_client()
    if client.count(version, exact=True).count != len(all_chunks):
        raise RuntimeError("Corpus point count mismatch; active collection is unchanged")
    alias = collection + "_active"
    changes = []
    if alias in {a.alias_name for a in client.get_aliases().aliases}:
        changes.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias)))
    changes.append(models.CreateAliasOperation(create_alias=models.CreateAlias(collection_name=version, alias_name=alias)))
    client.update_collection_aliases(change_aliases_operations=changes)
    logger.info("Готово. Всего проиндексировано: {} чанков в '{}'", total, collection)
    return total


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Индексация документов в RAG")
    parser.add_argument("path", help="Файл или директория с документами")
    parser.add_argument("--collection", default="law_kz", help="Имя Qdrant-коллекции")
    args = parser.parse_args()
    asyncio.run(index_path(args.path, collection=args.collection))


if __name__ == "__main__":
    main()
