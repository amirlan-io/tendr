/**
 * Карточка поставщика с посимвольной сверкой по пунктам ТЗ (F2–F3).
 *
 * Ключевое требование ТЗ: объяснение по пунктам показывается ПЕРВЫМ,
 * общий процент — вторичен. Поэтому здесь сначала таблица статусов,
 * а «87% соответствия» живёт в подписи и не заменяет разбор.
 */

import { useState } from "react";
import {
  MATCH_STATUS_CLASS,
  MATCH_STATUS_LABEL,
  formatKzt,
  type MatchStatus,
  type SupplierCandidate,
} from "../suppliers.types";

type Props = {
  candidate: SupplierCandidate;
  onFeedback?: (fits: boolean) => void;
  onDraft?: (kind: "email" | "call") => void;
  busy?: boolean;
};

export function SupplierCandidateCard({ candidate, onFeedback, onDraft, busy }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { card, requirement_matches: matches, warnings } = candidate;

  const fits = matches.filter((m) => m.status === "fits").length;
  const unknown = matches.filter((m) => m.status === "unknown").length;

  return (
    <article className="rounded-2xl border border-white/[0.08] bg-[#0a1115]/90">
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-base font-medium text-white/90">{candidate.title}</h3>
            <p className="mt-1 text-xs text-white/40">
              {candidate.supplier}
              {candidate.domain ? ` · ${candidate.domain}` : ""}
            </p>
          </div>
          {/* Общий балл вторичен — показываем подпись, а не «средний AI-процент». */}
          <div className="shrink-0 text-right">
            <div className="font-mono text-2xl font-light tracking-tight text-white/85">
              {candidate.score}
              <span className="text-sm text-white/30">/100</span>
            </div>
            <div className="mt-0.5 text-[10px] uppercase tracking-wider text-white/25">
              по пунктам ТЗ
            </div>
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-white/30">Цена</dt>
            <dd className="mt-0.5 font-medium text-white/75">{formatKzt(card.price_kzt)}</dd>
          </div>
          <div>
            <dt className="text-white/30">Наличие</dt>
            <dd className="mt-0.5 font-medium text-white/75">
              {card.in_stock === null ? "нет данных" : card.in_stock ? "в наличии" : "под заказ"}
            </dd>
          </div>
          <div>
            <dt className="text-white/30">Город</dt>
            <dd className="mt-0.5 font-medium text-white/75">{card.city || "—"}</dd>
          </div>
          <div>
            <dt className="text-white/30">Доставка</dt>
            <dd className="mt-0.5 font-medium text-white/75">
              {card.delivery_days ? `${card.delivery_days} дн` : "не указана"}
            </dd>
          </div>
        </dl>

        {/* Сверка по пунктам ТЗ — главное содержимое карточки. */}
        <section>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="flex w-full items-center justify-between rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2.5 text-left transition hover:border-white/15"
          >
            <span className="text-xs text-white/60">
              Проверка по ТЗ: <span className="text-emerald-300">{fits} подходит</span>
              {unknown > 0 && <span className="text-white/35"> · {unknown} нет данных</span>}
            </span>
            <span className="text-[10px] text-white/30">{expanded ? "Свернуть" : "Подробнее"}</span>
          </button>

          {expanded && (
            <ul className="mt-2 space-y-1.5">
              {matches.length === 0 && (
                <li className="text-xs text-white/35">
                  Требования не переданы — сверка не выполнялась.
                </li>
              )}
              {matches.map((m) => (
                <li key={`${m.code}-${m.title}`} className="flex items-start gap-2 text-xs">
                  <span
                    className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${
                      MATCH_STATUS_CLASS[m.status]
                    }`}
                  >
                    {MATCH_STATUS_LABEL[m.status]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-white/70">{m.title}</span>
                    {m.comment && <span className="mt-0.5 block text-white/35">{m.comment}</span>}
                    {m.source_url && (
                      <a
                        href={m.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-0.5 inline-block text-[10px] text-emerald-300/80 hover:underline"
                      >
                        Источник
                      </a>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {warnings.length > 0 && (
          <ul className="space-y-1 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3">
            {warnings.map((w) => (
              <li key={w} className="text-xs text-amber-200/80">
                {w}
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap gap-2 border-t border-white/[0.06] pt-3 text-xs text-white/45">
          {card.email && <span>✉ {card.email}</span>}
          {card.phone && <span>☎ {card.phone}</span>}
          {card.warranty && <span>Гарантия: {card.warranty}</span>}
          {card.certificates.length > 0 && (
            <span>Сертификаты: {card.certificates.join(", ")}</span>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onFeedback?.(true)}
            disabled={busy}
            aria-label={`Отметить «${candidate.supplier}» как подходящего`}
            className="rounded-lg border border-emerald-400/25 px-3 py-1.5 text-xs font-medium text-emerald-300 transition hover:bg-emerald-400/10 disabled:opacity-50"
          >
            Подходит
          </button>
          <button
            type="button"
            onClick={() => onFeedback?.(false)}
            disabled={busy}
            aria-label={`Отметить «${candidate.supplier}» как не подходящего`}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white/55 transition hover:bg-white/[0.05] disabled:opacity-50"
          >
            Не подходит
          </button>
          {onDraft && (
            <button
              type="button"
              onClick={() => onDraft("email")}
              disabled={busy}
              className="ml-auto rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white/60 transition hover:bg-white/[0.05] disabled:opacity-50"
            >
              Подготовить письмо
            </button>
          )}
          {onDraft && card.phone && (
            <button
              type="button"
              onClick={() => onDraft("call")}
              disabled={busy}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white/60 transition hover:bg-white/[0.05] disabled:opacity-50"
            >
              Подготовить звонок
            </button>
          )}
          {card.url && (
            <a
              href={card.url}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto text-xs text-white/40 underline-offset-2 hover:underline"
            >
              Страница поставщика
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

/** Группировка статусов для компактного отображения. */
export function summarizeMatches(matches: Array<{ status: MatchStatus }>): Record<MatchStatus, number> {
  const out: Record<MatchStatus, number> = { fits: 0, partial: 0, no: 0, unknown: 0 };
  for (const m of matches) out[m.status] += 1;
  return out;
}
