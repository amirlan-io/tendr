"""AI-анализ лотов: объединяет Documenter + Legal.

Используется для автогенерации ai_summary и ai_red_flags
в каталоге лотов (P0 из 3-го варианта).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from loguru import logger

from app.agents.documenter import DocumenterAgent
from app.agents.legal import LegalAgent
from app.schemas.lot import LotItem

logger = logging.getLogger(__name__)


class LotAnalyzer:
    """Объединяет Documenter + Legal для AI-анализа лотов из каталога.

    Использование:
        analyzer = LotAnalyzer()
        summary, red_flags, match_score = await analyzer.analyze_lot(lot_item)

    Возвращает:
        - summary: краткое описание лота (1-2 предложения)
        - red_flags: список рисков (3-5 пунктов)
        - match_score: 0-100 насколько лот подходит SMB
    """

    def __init__(self):
        self.documenter = DocumenterAgent()
        self.legal = LegalAgent()

    async def analyze_lot(self, lot: dict[str, Any]) -> tuple[str, list[str], int]:
        """
        Анализирует один лот.

        Args:
            lot: словарь с полями лота (title, description, amount_kzt, ...)

        Returns:
            (summary, red_flags, match_score)
        """
        title = lot.get("title") or ""
        description = lot.get("description") or ""
        amount = lot.get("amount_kzt") or 0
        region = lot.get("region") or ""
        category = lot.get("category") or ""
        organizer = lot.get("organizer") or ""

        # 1. Синтезируем "текст ТЗ" из данных лота
        lot_text = self._build_lot_text(lot)

        # 2. Documenter → структурированный анализ
        try:
            analysis = await self.documenter.run(
                lot_text=lot_text, lot_id=str(lot.get("id", "unknown"))
            )
            summary = self._extract_summary(analysis, lot)
        except Exception as e:
            logger.warning(f"[LotAnalyzer] Documenter failed: {e}")
            summary = self._fallback_summary(lot)
            analysis = None

        # 3. Legal → красные флаги
        try:
            if analysis is not None:
                # Синтезируем простой текст для Legal
                legal_text = f"""
                Название: {title}
                Описание: {description or "не указано"}
                Заказчик: {organizer}
                Регион: {region}
                Сумма: {amount} тенге
                Категория: {category}
                Срок: {lot.get("deadline_date", "не указан")}
                """
                legal_result = await self.legal.run(
                    lot_text=legal_text, lot_id=str(lot.get("id", "unknown"))
                )
                red_flags = self._extract_red_flags(legal_result, lot, analysis)
                match_score = self._calc_match_score(legal_result, lot, analysis)
            else:
                red_flags = self._fallback_red_flags(lot)
                match_score = self._fallback_match_score(lot)
        except Exception as e:
            logger.warning(f"[LotAnalyzer] Legal failed: {e}")
            red_flags = self._fallback_red_flags(lot)
            match_score = self._fallback_match_score(lot)

        return summary, red_flags, match_score

    async def analyze_batch(
        self, lots: list[dict[str, Any]], max_concurrent: int = 3
    ) -> list[tuple[str, list[str], int]]:
        """Параллельный анализ нескольких лотов (с ограничением concurrency)."""
        import asyncio

        sem = asyncio.Semaphore(max_concurrent)

        async def _one(lot):
            async with sem:
                return await self.analyze_lot(lot)

        return await asyncio.gather(*[_one(lot) for lot in lots])

    def _build_lot_text(self, lot: dict[str, Any]) -> str:
        """Собирает 'техзадание' из полей лота для Documenter."""
        parts = [
            f"Название лота: {lot.get('title', '')}",
            f"Описание: {lot.get('description') or 'не указано'}",
            f"Заказчик: {lot.get('organizer', 'не указан')}",
            f"Регион поставки: {lot.get('region', 'не указан')}",
            f"Адрес поставки: {lot.get('delivery_address', 'не указан')}",
            f"Сумма: {lot.get('amount_kzt', 0):,.0f} тенге"
            if lot.get("amount_kzt")
            else "Сумма: не указана",
            f"Категория: {lot.get('category', 'не указана')}",
            f"Способ закупки: {lot.get('procurement_method', 'не указан')}",
            f"Срок подачи: {lot.get('deadline_date', 'не указан')}",
            f"Площадка: {lot.get('platform', 'не указана')}",
        ]
        return "\n".join(parts)

    def _extract_summary(self, analysis: Any, lot: dict[str, Any]) -> str:
        """Извлекает summary из результата Documenter."""
        try:
            # Documenter возвращает LotAnalysis с полем title и др.
            # Делаем краткое описание 1-2 предложения
            title = getattr(analysis, "title", "") or lot.get("title", "")
            amount = lot.get("amount_kzt", 0)
            region = lot.get("region", "")
            category = lot.get("category", "")

            summary_parts = []
            if title:
                summary_parts.append(f"📦 {title[:120]}")
            if amount:
                summary_parts.append(f"💰 {amount:,.0f} ₸")
            if region:
                summary_parts.append(f"📍 {region}")
            if category:
                summary_parts.append(f"🏷 {category}")

            return " • ".join(summary_parts) or lot.get("title", "")[:120]
        except Exception:
            return self._fallback_summary(lot)

    def _extract_red_flags(
        self,
        legal_result: Any,
        lot: dict[str, Any],
        analysis: Any,
    ) -> list[str]:
        """Извлекает red flags из Legal Agent."""
        flags: list[str] = []

        try:
            # У Legal Agent есть checks: list[LegalCheckItem]
            checks = getattr(legal_result, "checks", []) or []
            for check in checks:
                severity = getattr(check, "severity", "info")
                if severity in ("violation", "warning"):
                    title = getattr(check, "title", "")
                    desc = getattr(check, "description", "")
                    if title:
                        flag = f"⚠️ {title}"
                        if desc:
                            flag += f": {desc[:80]}"
                        flags.append(flag)
        except Exception:
            pass

        # Дополнительные эвристические флаги по данным лота
        amount = lot.get("amount_kzt", 0) or 0
        if amount > 50_000_000:
            flags.append("💰 Крупный лот (50+ млн ₸) — нужна серьёзная подготовка")
        if amount < 100_000:
            flags.append("💸 Малый бюджет (< 100K ₸) — может не окупить затраты на заявку")

        deadline = lot.get("deadline_date")
        if deadline:
            from datetime import datetime

            try:
                if isinstance(deadline, str):
                    dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                else:
                    dl = deadline
                days_left = (dl - datetime.now(dl.tzinfo)).days
                if days_left < 3:
                    flags.append(f"⏰ Осталось {days_left} дн до дедлайна — мало времени")
                elif days_left < 7:
                    flags.append(f"⏰ {days_left} дн до дедлайна — поторопитесь")
            except Exception:
                pass

        region = lot.get("region", "")
        if not region or region == "Не задан":
            flags.append("🌍 Регион не указан — уточните у заказчика")

        organizer = lot.get("organizer", "")
        if not organizer:
            flags.append("🏛 Заказчик не указан")

        return flags[:6]  # максимум 6

    def _calc_match_score(
        self,
        legal_result: Any,
        lot: dict[str, Any],
        analysis: Any,
    ) -> int:
        """Считает match_score (0-100) насколько лот подходит SMB."""
        score = 70  # базовый

        try:
            # Штрафы за проблемы
            checks = getattr(legal_result, "checks", []) or []
            for check in checks:
                severity = getattr(check, "severity", "info")
                if severity == "violation":
                    score -= 25
                elif severity == "warning":
                    score -= 10
        except Exception:
            pass

        # Бонусы за хорошие параметры
        amount = lot.get("amount_kzt", 0) or 0
        if 1_000_000 <= amount <= 10_000_000:
            score += 15  # оптимальный размер для SMB
        elif 500_000 <= amount < 1_000_000:
            score += 5
        elif amount > 50_000_000:
            score -= 10  # слишком крупный

        # Бонус за наличие описания и контактов
        if lot.get("description"):
            score += 5
        if lot.get("organizer"):
            score += 5
        if lot.get("delivery_address"):
            score += 5

        return max(0, min(100, score))

    def _fallback_summary(self, lot: dict[str, Any]) -> str:
        """Fallback summary если AI не сработал."""
        title = (lot.get("title") or "")[:120]
        amount = lot.get("amount_kzt", 0) or 0
        region = lot.get("region", "")
        parts = [title] if title else []
        if amount:
            parts.append(f"{amount:,.0f} ₸")
        if region:
            parts.append(region)
        return " • ".join(parts) or "(описание недоступно)"

    def _fallback_red_flags(self, lot: dict[str, Any]) -> list[str]:
        """Fallback red flags без AI."""
        flags = []
        amount = lot.get("amount_kzt", 0) or 0
        if amount > 50_000_000:
            flags.append("💰 Крупный лот — серьёзная конкуренция")
        if not lot.get("organizer"):
            flags.append("🏛 Заказчик не указан")
        return flags

    def _fallback_match_score(self, lot: dict[str, Any]) -> int:
        """Fallback match score без AI."""
        score = 60
        amount = lot.get("amount_kzt", 0) or 0
        if 1_000_000 <= amount <= 10_000_000:
            score += 20
        if lot.get("description"):
            score += 5
        return min(100, score)
