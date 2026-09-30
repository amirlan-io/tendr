import { Plus, Search } from "lucide-react";
import { Link } from "react-router-dom";

/**
 * Мобильная навигация: кнопка «Новый анализ» доступна и на маленьких экранах
 * (в шапке она скрыта), плюс быстрый переход к поиску лотов.
 */
export function DashboardMobileNav() {
  return (
    <nav
      aria-label="Быстрые действия"
      className="fixed bottom-0 left-0 right-0 z-30 flex items-center justify-around gap-2 border-t border-white/[0.065] bg-[#111112]/95 px-4 py-3 backdrop-blur-xl sm:hidden"
    >
      <Link
        to="/dashboard/analyze"
        className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-[8px] bg-white px-4 text-xs font-semibold text-[#111112]"
      >
        <Plus aria-hidden className="h-4 w-4" />
        Новый анализ
      </Link>
      <Link
        to="/dashboard/lots"
        aria-label="Найти лоты"
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-[8px] border border-white/[0.08] bg-white/[0.035] px-4 text-xs font-medium text-white/70"
      >
        <Search aria-hidden className="h-4 w-4" />
        Лоты
      </Link>
    </nav>
  );
}
