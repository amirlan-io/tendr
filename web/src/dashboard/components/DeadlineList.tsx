import { Link } from "react-router-dom";
import type { DeadlineItem } from "../dashboard.types";
import { EmptyState } from "./EmptyState";

const URGENCY: Record<DeadlineItem["urgency"], { label: string; className: string }> = {
  overdue: { label: "Просрочен", className: "text-red-300 bg-red-400/[0.07] border-red-400/15" },
  urgent: { label: "Срочно", className: "text-red-300 bg-red-400/[0.07] border-red-400/15" },
  soon: { label: "Скоро", className: "text-[#d6bb63] bg-[#d6bb63]/[0.06] border-[#d6bb63]/15" },
  normal: { label: "В срок", className: "text-emerald-300 bg-emerald-400/[0.06] border-emerald-400/15" },
};

export function DeadlineList({ items }: { items: DeadlineItem[] }) {
  return (
    <section
      aria-label="Ближайшие дедлайны"
      className="overflow-hidden rounded-xl border border-white/[0.075] bg-[#121213]/90"
    >
      <div className="border-b border-white/[0.07] px-5 py-5 sm:px-6">
        <p className="text-sm font-medium text-white">Ближайшие дедлайны</p>
        <p className="mt-1 text-xs text-white/30">Сохранённые закупки с датой завершения</p>
      </div>
      {items.length === 0 ? (
        <EmptyState
          title="Дедлайнов нет"
          text="Сохраните лот из поиска — его дата завершения появится здесь."
          actionTo="/dashboard/lots"
          actionLabel="Найти лоты"
        />
      ) : (
        <ul className="divide-y divide-white/[0.06]">
          {items.map((item) => {
            const u = URGENCY[item.urgency];
            return (
              <li key={item.id}>
                <Link
                  to={item.to}
                  className="grid gap-2 px-5 py-4 transition hover:bg-white/[0.02] focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 sm:px-6"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white/80">{item.title}</p>
                    <p className="mt-1 truncate text-[11px] text-white/25">
                      {item.customer} · до {item.deadlineDate}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] text-white/25">
                      {item.daysLeft <= 0 ? "сегодня" : `осталось ${item.daysLeft} дн.`}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[9px] ${u.className}`}>
                      {u.label}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
