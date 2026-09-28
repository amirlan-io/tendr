import { Link } from "react-router-dom";
import { DashboardIcon } from "./DashboardIcon";

/**
 * Мобильная навигация: кнопка «Новый анализ» доступна и на маленьких экранах
 * (в шапке она скрыта), плюс быстрый переход к поиску лотов.
 */
export function DashboardMobileNav() {
  return (
    <nav
      aria-label="Быстрые действия"
      className="fixed bottom-0 left-0 right-0 z-30 flex items-center justify-around gap-2 border-t border-white/[0.07] bg-[#080e12]/95 px-4 py-3 backdrop-blur-xl sm:hidden"
    >
      <Link
        to="/dashboard/analyze"
        className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-400 px-4 text-xs font-semibold text-[#03110b]"
      >
        <DashboardIcon name="plus" />
        Новый анализ
      </Link>
      <Link
        to="/dashboard/lots"
        aria-label="Найти лоты"
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.025] px-4 text-xs font-medium text-white/70"
      >
        <DashboardIcon name="search" />
        Лоты
      </Link>
    </nav>
  );
}
