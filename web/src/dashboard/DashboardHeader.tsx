import { Menu, PanelLeftClose, PanelLeftOpen, Plus, Search } from "lucide-react";
import { Link } from "react-router-dom";

type Props = {
  title: string;
  breadcrumb: string[];
  initials: string;
  onOpenMobile: () => void;
  onOpenSearch: () => void;
  onToggleCollapse: () => void;
  collapsed: boolean;
};

export function DashboardHeader({
  title,
  breadcrumb,
  initials,
  onOpenMobile,
  onOpenSearch,
  onToggleCollapse,
  collapsed,
}: Props) {
  return (
    <header className="sticky top-0 z-30 flex h-[58px] items-center justify-between border-b border-white/[0.065] bg-[#111112]/95 px-4 backdrop-blur-xl sm:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <button
          aria-label="Открыть меню"
          onClick={onOpenMobile}
          className="rounded-[7px] p-2 text-white/45 transition-colors hover:bg-white/[0.055] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60 lg:hidden"
        >
          <Menu aria-hidden className="h-[17px] w-[17px]" strokeWidth={1.6} />
        </button>
        <button
          aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
          onClick={onToggleCollapse}
          className="hidden rounded-[7px] p-2 text-white/35 transition-colors hover:bg-white/[0.055] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60 lg:block"
        >
          {collapsed ? (
            <PanelLeftOpen aria-hidden className="h-[17px] w-[17px]" strokeWidth={1.55} />
          ) : (
            <PanelLeftClose aria-hidden className="h-[17px] w-[17px]" strokeWidth={1.55} />
          )}
        </button>
        <nav aria-label="Хлебные крошки" className="hidden min-w-0 items-center gap-2 text-[12px] sm:flex">
          {breadcrumb.map((crumb, i) => (
            <span key={crumb} className="flex shrink-0 items-center gap-2">
              {i > 0 && <span className="text-white/15">/</span>}
              <span className={i === breadcrumb.length - 1 ? "font-medium text-white/85" : "text-white/30"}>
                {crumb}
              </span>
            </span>
          ))}
        </nav>
        <h1 className="truncate text-sm font-semibold text-white sm:hidden">{title}</h1>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Открыть поиск"
          onClick={onOpenSearch}
          className="hidden h-9 w-[clamp(160px,22vw,260px)] items-center gap-2 rounded-[7px] border border-white/[0.045] bg-white/[0.035] px-3 text-left text-[11px] text-white/25 transition-colors hover:border-white/[0.09] hover:bg-white/[0.055] hover:text-white/45 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60 md:flex"
        >
          <Search aria-hidden className="h-3.5 w-3.5" strokeWidth={1.6} />
          <span className="flex-1">Найти раздел</span>
          <kbd className="font-mono text-[9px] text-white/18">Ctrl K</kbd>
        </button>
        <Link
          to="/dashboard/analyze"
          className="hidden h-9 items-center gap-2 rounded-[7px] bg-white px-3.5 text-[11px] font-semibold text-[#111112] transition hover:bg-white/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:inline-flex"
        >
          <Plus aria-hidden className="h-3.5 w-3.5" strokeWidth={1.8} />
          Новый анализ
        </Link>
        <Link
          to="/dashboard/settings"
          aria-label="Профиль пользователя"
          className="flex h-9 w-9 items-center justify-center rounded-full border border-white/[0.11] bg-white/[0.055] text-[10px] font-semibold text-white/75 transition-colors hover:bg-white/[0.09] hover:text-white"
        >
          {initials}
        </Link>
      </div>
    </header>
  );
}
