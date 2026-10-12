import { Link } from "react-router-dom";
import type { ActivityItem } from "../dashboard.types";
import { EmptyState } from "./EmptyState";
import { resolveLotSourceUrl } from "./LotSourceLink";

const KIND_LABEL: Record<ActivityItem["kind"], string> = {
  analysis: "Анализ",
  lot: "Лот",
  document: "Документ",
};

export function RecentActivity({ items }: { items: ActivityItem[] }) {
  return (
    <section
      aria-label="Последние активности"
      className="overflow-hidden rounded-xl border border-white/[0.075] bg-[#121213]/90"
    >
      <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-5 sm:px-6">
        <div>
          <p className="text-sm font-medium text-white">Последние активности</p>
          <p className="mt-1 text-xs text-white/30">Анализы, лоты и документы</p>
        </div>
        <Link
          to="/dashboard/history"
          className="rounded-lg px-2 py-1 text-xs font-medium text-emerald-300 hover:text-emerald-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
        >
          Посмотреть все
        </Link>
      </div>
      {items.length === 0 ? (
        <EmptyState
          title="Пока тихо"
          text="Здесь появятся ваши анализы, сохранённые лоты и подготовленные документы."
          actionTo="/dashboard/analyze"
          actionLabel="Начать анализ"
        />
      ) : (
        <ul className="divide-y divide-white/[0.06]">
          {items.map((item) => {
            const lotUrl = resolveLotSourceUrl(item.sourceUrl, item.lotId);
            return (
            <li key={item.id} className="flex items-stretch">
              <Link
                to={item.to}
                className="grid flex-1 gap-2 px-5 py-4 transition hover:bg-white/[0.02] focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 sm:grid-cols-[1fr_auto] sm:items-center sm:px-6"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white/80">{item.title}</p>
                  <p className="mt-1 truncate text-[11px] text-white/25">
                    {KIND_LABEL[item.kind]} · {item.subtitle}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-white/25">{item.createdAt}</span>
                  <span className="rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[9px] text-white/45">
                    {item.status}
                  </span>
                </div>
              </Link>
              {lotUrl && (
                <a
                  href={lotUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Открыть источник объявления ${item.lotId ?? ""}`}
                  title="Открыть объявление на Госзакупках"
                  className="flex shrink-0 items-center px-4 text-white/25 transition hover:text-white/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
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
              )}
            </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
