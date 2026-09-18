"""FSM для incomplete-флоу: когда парсер не нашёл данные, просим прислать файл."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from bot.keyboards import main_menu
from bot.locales import t

router = Router(name="incomplete")


class WaitFile(StatesGroup):
    waiting_for_file = State()


def _make_attach_keyboard(lang: str = "ru"):
    """Inline-кнопки: прикрепить файл / пропустить."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=t("btn_attach_file", lang),
            callback_data="attach_file",
        ),
        InlineKeyboardButton(
            text=t("btn_skip", lang),
            callback_data="attach_skip",
        ),
    )
    return kb.as_markup()


@router.callback_query(F.data == "attach_file")
async def cb_attach(cb: CallbackQuery, state: FSMContext) -> None:
    """Пользователь нажал «Прикрепить файл» — переходим в FSM."""
    lang = "ru"  # TODO: брать из FSM
    await state.set_state(WaitFile.waiting_for_file)
    await cb.message.answer(t("waiting_file", lang))
    await cb.answer()


@router.callback_query(F.data == "attach_skip")
async def cb_attach_skip(cb: CallbackQuery, state: FSMContext) -> None:
    """Пользователь нажал «Пропустить»."""
    await state.clear()
    lang = "ru"
    await cb.message.answer(
        t("ok", lang)
        if "ok" in t.__dict__.get("__doc__", "") or False
        else "Хорошо, вернёмся к меню.",
        reply_markup=main_menu(lang),
    )
    await cb.answer()
