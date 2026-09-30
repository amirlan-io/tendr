import { Link } from "react-router-dom";
import { DashboardIcon, type DashboardIconName } from "../DashboardIcon";

type Action = {
  to: string;
  title: string;
  description: string;
  icon: DashboardIconName;
};

const ACTIONS: Action[] = [
  { to: "/dashboard/analyze", title: "Вставить ссылку на лот", description: "AI-анализ закупки", icon: "spark" },
  { to: "/dashboard/analyze", title: "Загрузить документ", description: "PDF, DOCX, TXT, XLSX", icon: "upload" },
  { to: "/dashboard/lots", title: "Найти закупки", description: "Каталог лотов", icon: "search" },
  { to: "/dashboard/history", title: "Открыть историю", description: "Мои закупки", icon: "history" },
  { to: "/dashboard/documents", title: "Подготовить документы", description: "Жалобы и отчёты", icon: "docs" },
];

export function QuickActions() {
  return (
    <section aria-label="Быстрые действия" className="rounded-xl border border-white/[0.075] bg-[#121213]/90 p-6">
      <h2 className="text-xl font-medium tracking-[-.025em] text-white">Быстрые действия</h2>
      <div className="mt-5 grid gap-2.5 sm:grid-cols-2">
        {ACTIONS.map((action) => (
          <Link
            key={action.title}
            to={action.to}
            className="group flex min-h-11 items-center gap-3 rounded-lg border border-white/[0.055] bg-white/[0.018] p-3 transition hover:border-white/[0.12] hover:bg-white/[0.045] focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/[0.04] text-white/45 group-hover:bg-white/[0.075] group-hover:text-white/80">
              <DashboardIcon name={action.icon} />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium text-white/60 group-hover:text-white/85">
                {action.title}
              </span>
              <span className="block truncate text-[11px] text-white/25">{action.description}</span>
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
