"""Скрипт для индексации нормативной базы в RAG.

Использование:
    python -m app.rag.indexer <путь_к_файлу_или_директории>

Поддерживает .pdf, .docx, .txt, .md. Рекурсивно обходит директории.
Результат: чанки уходят в Qdrant-коллекцию "law_kz".
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from loguru import logger

from app.core.logging import setup_logging
from app.rag import RAGStore, split_into_chunks
from app.services.document_reader import extract_text

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


async def index_path(path: str | Path, collection: str = "law_kz") -> int:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    files = list(p.rglob("*")) if p.is_dir() else [p]
    files = [f for f in files if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES]
    if not files:
        logger.warning("Нет подходящих файлов в {}", p)
        return 0

    store = RAGStore(collection=collection)
    total = 0
    for f in files:
        logger.info("Индексирую {}", f)
        text = await extract_text(f)
        chunks = split_into_chunks(
            text,
            source=str(f.relative_to(p.parent if p.is_dir() else p.parent)),
            metadata={"filename": f.name, "kind": "law"},
        )
        logger.info("  {} чанков, индексирую…", len(chunks))
        n = await store.upsert(chunks)
        logger.info("  → {} чанков добавлено", n)
        total += n
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
