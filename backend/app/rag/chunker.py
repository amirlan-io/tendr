"""Разбиение длинных текстов на чанки для RAG.

Стратегия: рекурсивный split по абзацам/предложениям с сохранением контекста.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    source: str  # откуда (имя файла / URL)
    chunk_id: str  # уникальный ID
    metadata: dict


def split_into_chunks(
    text: str,
    *,
    source: str,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    base_id: str | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Рекурсивно делит текст на чанки размером ~chunk_size символов.

    Эвристика: сначала режем по двойным переводам строк (абзацы),
    потом по одиночным (предложения), склеиваем обратно до chunk_size.
    """
    text = re.sub(r"\r\n", "\n", text).strip()
    if not text:
        return []

    base_id = base_id or _slugify(source)
    metadata = metadata or {}
    parts = _split_recursive(text, separators=["\n\n", "\n", ". ", " "], chunk_size=chunk_size)
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    counter = 0

    def flush() -> None:
        nonlocal buf, buf_len, counter
        if not buf:
            return
        joined = " ".join(buf).strip()
        if joined:
            chunks.append(
                Chunk(
                    text=joined,
                    source=source,
                    chunk_id=f"{base_id}::{counter:04d}",
                    metadata={**metadata, "position": counter},
                )
            )
            counter += 1
        buf = []
        buf_len = 0

    for part in parts:
        if buf_len + len(part) > chunk_size and buf:
            flush()
        if len(part) > chunk_size:
            # совсем длинный кусок — режем по предложениям
            for sentence in re.split(r"(?<=[.!?])\s+", part):
                if buf_len + len(sentence) > chunk_size and buf:
                    flush()
                buf.append(sentence)
                buf_len += len(sentence)
        else:
            buf.append(part)
            buf_len += len(part)
    flush()

    # добавим overlap: каждый следующий чанк начинается с хвоста предыдущего
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[Chunk] = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev.text[-chunk_overlap:]
            overlapped.append(
                Chunk(
                    text=(tail + " " + cur.text)[: chunk_size + chunk_overlap],
                    source=cur.source,
                    chunk_id=cur.chunk_id,
                    metadata=cur.metadata,
                )
            )
        chunks = overlapped

    return chunks


def _split_recursive(text: str, separators: list[str], chunk_size: int) -> list[str]:
    if not separators or len(text) <= chunk_size:
        return [text]
    sep = separators[0]
    parts = text.split(sep)
    out: list[str] = []
    for p in parts:
        if len(p) <= chunk_size:
            out.append(p)
        else:
            out.extend(_split_recursive(p, separators[1:], chunk_size))
    return out


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s)
    return s.strip("_")[:80] or "doc"
