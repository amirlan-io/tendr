"""Vision-анализ изображений из PDF/DOCX через Mistral.

Использует mistral-large-latest (поддерживает vision на бесплатном тарифе).
На выходе — текстовое описание каждой картинки, которое добавляется в контекст LLM.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from loguru import logger
from pypdf import PdfReader

from app.core.config import get_settings

# Системный промпт для vision-анализа
_VISION_PROMPT = """Ты эксперт по государственным закупкам и технической документации.
У тебя изображение из технического задания (ТЗ) на закупку. Твоя задача — дать
подробное описание, которое поможет закупающей организации или поставщику.

Опиши:
1. Что изображено (чертёж, фото, схема, диаграмма)
2. Если чертёж — все размеры (мм) с подписями, что за изделие
3. Если фото — как выглядит в реальности, особенности конструкции
4. Технические характеристики, которые видны
5. На что обратить внимание при закупке

Формат: 2-4 предложения, конкретика, без воды. Если на картинке ничего полезного — напиши '[не информативно]'."""


def _encode_image(path: str | Path) -> tuple[str, str]:
    """Кодирует картинку в base64 + определяет mime-type."""
    p = Path(path)
    suffix = p.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    with open(p, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode("utf-8"), mime


def describe_image(path: str | Path) -> str:
    """Описывает одну картинку через Mistral Vision. Возвращает текст."""
    from mistralai.client import Mistral

    settings = get_settings()

    # 1. qwen3-6 (основная) — vision работает, лучше на чертежах
    if settings.llm_api_key_fallback and settings.alem_base_url:
        try:
            from openai import OpenAI

            b64, mime = _encode_image(path)
            client = OpenAI(
                api_key=settings.llm_api_key_fallback,
                base_url=settings.alem_base_url,
            )
            resp = client.chat.completions.create(
                model=settings.alem_model or "qwen3-6",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _VISION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            },
                        ],
                    }
                ],
                max_tokens=300,
                temperature=0.2,
                # Отключаем thinking mode — без этого qwen3-6 не отвечает
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            content = resp.choices[0].message.content
            if content and content.strip():
                return content.strip()
        except Exception as e:
            logger.warning("qwen3-6 vision failed: {}", e)

    # 2. Mistral Large (fallback)
    if settings.llm_api_key:
        try:
            from mistralai.client import Mistral

            b64, mime = _encode_image(path)
            client = Mistral(api_key=settings.llm_api_key)
            resp = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _VISION_PROMPT},
                            {"type": "image_url", "image_url": f"data:{mime};base64,{b64}"},
                        ],
                    }
                ],
                max_tokens=300,
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Mistral vision failed: {}", e)

    return "[vision недоступен — нет работающих API-ключей]"


def extract_images_from_pdf(pdf_path: str | Path, out_dir: str | Path) -> list[Path]:
    """Извлекает все картинки из PDF в указанную папку.

    Returns: список путей к сохранённым картинкам.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    try:
        reader = PdfReader(str(pdf_path))
        for page_idx, page in enumerate(reader.pages, 1):
            for img_idx, img in enumerate(page.images):
                out = out_dir / f"page{page_idx}_img{img_idx + 1}_{img.name}"
                out.write_bytes(img.data)
                paths.append(out)
    except Exception as e:
        logger.warning("PDF image extraction failed for {}: {}", pdf_path, e)
    return paths


async def describe_pdf_images(pdf_path: str | Path, max_images: int = 5) -> str:
    """Извлекает картинки из PDF и описывает каждую через Vision.

    Возвращает одну строку с описаниями всех картинок для контекста LLM.
    """
    import tempfile

    pdf_path = Path(pdf_path)
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return ""

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        paths = extract_images_from_pdf(pdf_path, out_dir)
        if not paths:
            return ""
        # Описываем максимум max_images
        parts: list[str] = []
        for i, p in enumerate(paths[:max_images], 1):
            try:
                desc = describe_image(p)
                if desc and not desc.startswith("["):
                    parts.append(f"[Картинка {i}]: {desc}")
            except Exception as e:
                logger.warning("Describe image {} failed: {}", p, e)
        if parts:
            return "\n".join(parts)
        return ""
