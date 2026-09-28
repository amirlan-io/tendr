import { Link } from "react-router-dom";
import { DashboardIcon } from "./DashboardIcon";

type Props = {
  title: string;
  breadcrumb: string[];
  initials: string;
  onOpenMobile: () => void;
  onToggleCollapse: () => void;
  collapsed: boolean;
};

export function DashboardHeader({
  title,
  breadcrumb,
  initials,
  onOpenMobile,
  onToggleCollapse,
  collapsed,
}: Props) {
  return (
    <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between border-b border-white/[0.07] bg-[#060b0e]/80 px-4 backdrop-blur-xl sm:px-7">
      <div className="flex min-w-0 items-center gap-3">
        <button
          aria-label="Открыть меню"
          onClick={onOpenMobile}
          className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-2.5 text-white/60 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 lg:hidden"
        >
          <DashboardIcon name="menu" />
        </button>
        <button
          aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
          onClick={onToggleCollapse}
          className="hidden rounded-xl border border-white/[0.08] bg-white/[0.025] p-2.5 text-white/45 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 lg:block"
        >
          <DashboardIcon name="menu" />
        </button>
        <nav aria-label="Хлебные крошки" className="hidden min-w-0 items-center gap-2 text-xs sm:flex">
          {breadcrumb.map((crumb, i) => (
            <span key={crumb} className="flex shrink-0 items-center gap-2">
              {i > 0 && <span className="text-white/15">/</span>}
              <span className={i === breadcrumb.length - 1 ? "font-medium text-white/75" : "text-white/30"}>
                {crumb}
              </span>
            </span>
          ))}
        </nav>
        <h1 className="truncate text-sm font-semibold text-white sm:hidden">{title}</h1>
      </div>
      <div className="flex items-center gap-3">
        <Link
          to="/dashboard/analyze"
          className="hidden items-center gap-2 rounded-xl bg-emerald-400 px-4 py-2.5 text-xs font-semibold text-[#03110b] transition hover:bg-emerald-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400 sm:inline-flex"
        >
          <DashboardIcon name="plus" />
          Новый анализ
        </Link>
        <div
          aria-label="Профиль пользователя"
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.07] text-xs font-semibold text-emerald-300"
        >
          {initials}
        </div>
      </div>
    </header>
  );
}
