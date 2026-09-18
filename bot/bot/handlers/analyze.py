"""Обработчик анализа лота: ссылка или файл."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import httpx
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.handlers.incomplete import _make_attach_keyboard
from bot.keyboards import main_menu
from bot.locales import t

router = Router(name="analyze")

URL_RE = re.compile(r"https?://[^\s]+|^\d{6,}$")


def _get_user_lang(state) -> str:  # noqa: ANN001
    # TODO: вынести хранение языка в FSM/БД
    return "ru"


def _format_analysis(data: dict, lang: str) -> str:
    """Сформировать краткую сводку."""
    lot = data.get("lot", {}) or {}
    legal = data.get("legal") or {}
    return t(
        "analysis_done",
        lang,
        title=lot.get("title", "—"),
        customer=lot.get("customer", "—"),
        budget=lot.get("budget_kzt") or "—",
        deadline=lot.get("deadline") or "—",
        n_req=len(lot.get("requirements", []) or []),
        n_flags=len(lot.get("red_flags", []) or []),
        risk=legal.get("overall_risk", "—") if isinstance(legal, dict) else "—",
        summary=lot.get("summary", "") or "",
    )


def _format_full_report(data: dict, lang: str) -> list[str]:
    """Разбить подробности на секции (Telegram-лимит 4096 символов на сообщение)."""
    lot = data.get("lot", {}) or {}
    legal = data.get("legal") or {}
    sections: list[str] = []

    sections.append(t("full_report_header", lang, lot_id=lot.get("lot_id", "—")))

    reqs = lot.get("requirements") or []
    if reqs:
        block = t("requirements_title", lang) + "\n"
        for r in reqs[:10]:
            if not isinstance(r, dict):
                continue
            title = r.get("title") or r.get("description") or "—"
            block += f"• {title}\n"
        sections.append(block)

    flags = lot.get("red_flags") or []
    if flags:
        block = t("red_flags_title", lang) + "\n"
        for f in flags[:10]:
            block += f"• {f}\n"
        sections.append(block)

    docs = lot.get("documents_required") or []
    if docs:
        block = t("documents_title", lang) + "\n"
        for d in docs[:15]:
            block += f"• {d}\n"
        sections.append(block)

    items = (legal or {}).get("items") or []
    if items:
        block = t("violations_title", lang) + "\n"
        for it in items[:10]:
            if not isinstance(it, dict):
                continue
            ref = it.get("law_reference") or it.get("rule_id") or "—"
            desc = it.get("description") or it.get("rule_title") or ""
            block += f"• *{ref}*: {desc[:200]}\n"
        sections.append(block)

    draft = (legal or {}).get("complaint_draft")
    if isinstance(draft, dict):
        block = t("complaint_draft_title", lang) + "\n"
        for k in ("шапка", "обстоятельства", "нарушенные_нормы", "просьба"):
            v = draft.get(k)
            if v:
                block += f"\n*{k}*:\n{v[:1500]}\n"
        sections.append(block)
    elif isinstance(draft, str) and draft.strip():
        sections.append(t("complaint_draft_title", lang) + "\n" + draft[:3000])

    return [s for s in sections if s.strip()]


async def _send_details(message: Message, data: dict, lang: str) -> None:
    """Отправить подробные секции отдельными сообщениями."""
    for chunk in _format_full_report(data, lang):
        try:
            await message.answer(chunk, parse_mode="Markdown")
        except Exception:  # noqa: BLE001
            await message.answer(chunk)


@router.callback_query(F.data == "analyze_url")
async def cb_analyze_url(cb: CallbackQuery) -> None:
    lang = _get_user_lang(cb)
    await cb.message.answer(t("ask_url", lang))
    await cb.answer()


@router.message(F.text.regexp(URL_RE))
async def handle_url(message: Message) -> None:
    """Пользователь прислал ссылку или ID лота."""
    lang = _get_user_lang(message)
    s = get_settings()
    wait = await message.answer(t("processing", lang))

    # API ожидает поле `url` (AnalyzeLotRequest). Если прислали просто ID —
    # подставляем его как URL, парсер сам извлечёт числовой ID.
    raw_text = (message.text or "").strip()
    url_value = raw_text if raw_text.startswith("http") else f"id:{raw_text}"
    payload = {"url": url_value}
    # Уникальный client_id для бота — чтобы квота считалась на пользователя TG.
    client_id = f"tg:{message.from_user.id}" if message.from_user else "tg:anon"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{s.backend_url}/api/lots/analyze",
                json=payload,
                headers={"X-Client-Id": client_id},
            )
        if resp.status_code == 402:
            await wait.edit_text(t("quota_exceeded", lang))
            return
        if resp.status_code != 200:
            await wait.edit_text(t("error", lang, error=resp.text[:500]))
            return
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        await wait.edit_text(t("error", lang, error=str(e)))
        return

    if data.get("incomplete"):
        await wait.edit_text(
            t("incomplete_data", lang, reason=data.get("incomplete_reason") or "—"),
            parse_mode="Markdown",
            reply_markup=_make_attach_keyboard(lang),
        )
        return

    await wait.edit_text(
        _format_analysis(data, lang),
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )
    await _send_details(message, data, lang)


@router.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    """Пользователь прислал файл (PDF/DOCX)."""
    lang = _get_user_lang(message)
    s = get_settings()
    doc = message.document
    if not doc:
        return
    if doc.mime_type not in {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
    }:
        await message.answer(
            t("error", lang, error="Поддерживаются PDF, DOCX, TXT, XLSX, XLS, CSV.")
        )
        return

    wait = await message.answer(t("processing", lang))
    client_id = f"tg:{message.from_user.id}" if message.from_user else "tg:anon"
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / (doc.file_name or "tz.pdf")
        await bot.download(doc, destination=file_path)
        try:
            # В бэкенде нет отдельного /analyze-upload эндпоинта.
            # Используем существующий /api/lots/analyze с url=file://... не подходит,
            # поэтому читаем файл локально и отправляем через multipart на
            # /api/lots/analyze-upload если он появится. Сейчас — информируем пользователя.
            #
            # Альтернатива: вызвать /api/lots/analyze с url="id:uploaded" и потом
            # через /api/lots/{id}/partnership приложить файл — но это не реализовано.
            #
            # На данный момент: сообщаем пользователю что загрузка файлов через
            # бота временно не поддерживается, и предлагаем прислать URL.
            async with httpx.AsyncClient(timeout=180) as client:
                # Попробуем сначала /api/lots/analyze-upload (если когда-то добавим)
                with open(file_path, "rb") as f:
                    resp = await client.post(
                        f"{s.backend_url}/api/lots/analyze-upload",
                        files={"file": (file_path.name, f, doc.mime_type)},
                        headers={"X-Client-Id": client_id},
                    )
                # Если эндпоинт не существует (404) — просим прислать URL
                if resp.status_code == 404:
                    await wait.edit_text(
                        "Загрузка файлов через бота временно не поддерживается. "
                        "Пришлите, пожалуйста, URL лота с goszakup.gov.kz "
                        "или ID объявления (число из ссылки)."
                    )
                    return
            if resp.status_code == 402:
                await wait.edit_text(t("quota_exceeded", lang))
                return
            if resp.status_code != 200:
                await wait.edit_text(t("error", lang, error=resp.text[:500]))
                return
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            await wait.edit_text(t("error", lang, error=str(e)))
            return

    if data.get("incomplete"):
        await wait.edit_text(
            t("incomplete_data", lang, reason=data.get("incomplete_reason") or "—"),
            parse_mode="Markdown",
            reply_markup=main_menu(lang),
        )
        return

    await wait.edit_text(
        _format_analysis(data, lang),
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )
    await _send_details(message, data, lang)
