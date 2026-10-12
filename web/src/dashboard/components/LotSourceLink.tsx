/**
 * Переход на оригинальное объявление на площадке закупок.
 *
 * Раньше ссылка была вкопирована в каждую страницу отдельно, из-за чего
 * она молча пропадала там, где известен только числовой ID лота (история,
 * дедлайны, документы) — пользователь не мог вернуться к источнику.
 *
 * Здесь единственная точка решения: сначала пробуем готовый source_url
 * (проходит строгий allowlist хоста), затем строим ссылку из ID.
 * Если нет ни того, ни другого — компонент не рендерится вовсе.
 */

import { buildGoszakupUrl, getSafeExternalUrl } from "../../security/externalUrl";

export function resolveLotSourceUrl(
  sourceUrl?: string | null,
  lotId?: string | null,
): string | null {
  const direct = getSafeExternalUrl(sourceUrl);
  if (direct) return direct;
  return getSafeExternalUrl(buildGoszakupUrl(lotId));
}

type Props = {
  sourceUrl?: string | null;
  lotId?: string | null;
  /** Текст на кнопке. Для компактных мест передайте className с маленьким текстом. */
  label?: string;
  className?: string;
  title?: string;
};

/** Кнопка-ссылка «Открыть лот ↗». */
export function LotSourceLink({
  sourceUrl,
  lotId,
  label = "Открыть лот ↗",
  className = "",
  title,
}: Props) {
  const url = resolveLotSourceUrl(sourceUrl, lotId);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={title ?? `Открыть объявление ${lotId ?? ""} на Госзакупках`.trim()}
      className={
        className ||
        "inline-flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-xs text-white/70 transition hover:border-white/25 hover:text-white"
      }
    >
      {label}
    </a>
  );
}

/** Компактная иконочная кнопка для плотных списков (карточки лотов). */
export function LotSourceIconButton({
  sourceUrl,
  lotId,
  className = "",
}: Props) {
  const url = resolveLotSourceUrl(sourceUrl, lotId);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Открыть лот ${lotId ?? ""} на Госзакупках`}
      title="Открыть источник"
      className={
        className ||
        "inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.09] text-white/42 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white"
      }
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M7 17 17 7M9 7h8v8" />
      </svg>
    </a>
  );
}
