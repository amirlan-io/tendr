import { Link, NavLink } from "react-router-dom";
import { DASHBOARD_NAV } from "./dashboard.data";
import { DashboardIcon } from "./DashboardIcon";

type Props = {
  email: string | null;
  displayName: string;
  initials: string;
  tariffLabel: string;
  collapsed: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onSignOut: () => void;
};

export function DashboardSidebar({
  email,
  displayName,
  initials,
  tariffLabel,
  collapsed,
  mobileOpen,
  onCloseMobile,
  onSignOut,
}: Props) {
  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Закрыть меню"
          className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm lg:hidden"
          onClick={onCloseMobile}
        />
      )}
      <aside
        aria-label="Навигация кабинета"
        className={`fixed inset-y-0 left-0 z-50 flex border-r border-white/[0.075] bg-[#080e12]/95 backdrop-blur-2xl transition-all duration-300 ${
          collapsed ? "w-[84px]" : "w-[268px]"
        } ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}
      >
        <div className="flex min-w-0 flex-1 flex-col p-3">
          <div
            className={`flex h-14 items-center ${collapsed ? "justify-center" : "justify-between px-2"}`}
          >
            <Link to="/dashboard" className="flex min-w-0 items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 text-sm font-bold text-[#03100b]">
                T
              </span>
              {!collapsed && (
                <span className="truncate text-[17px] font-semibold tracking-[-.03em] text-white">
                  Tendr
                </span>
              )}
            </Link>
            {!collapsed && (
              <button
                aria-label="Закрыть меню"
                onClick={onCloseMobile}
                className="rounded-lg p-2 text-white/35 hover:bg-white/[0.05] hover:text-white lg:hidden"
              >
                <DashboardIcon name="close" />
              </button>
            )}
          </div>

          <div
            className={`mt-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] ${collapsed ? "p-2" : "p-3"}`}
          >
            <div className={`flex items-center ${collapsed ? "justify-center" : "gap-3"}`}>
              <span
                aria-hidden
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/[0.08] text-xs font-semibold text-emerald-300"
              >
                {initials}
              </span>
              {!collapsed && (
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-white">{displayName}</p>
                  <p className="truncate text-[11px] text-white/35">{email ?? ""}</p>
                  <p className="mt-1 text-[10px] uppercase tracking-[.12em] text-white/30">
                    {tariffLabel}
                  </p>
                </div>
              )}
            </div>
          </div>

          <nav className="mt-6 flex-1 space-y-1" aria-label="Разделы кабинета">
            {!collapsed && (
              <p className="mb-3 px-3 text-[9px] font-semibold uppercase tracking-[.18em] text-white/25">
                Рабочее пространство
              </p>
            )}
            {DASHBOARD_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/dashboard"}
                onClick={onCloseMobile}
                className={({ isActive }) =>
                  `group flex min-h-11 items-center rounded-xl border transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${
                    collapsed ? "justify-center px-2" : "gap-3 px-3"
                  } ${
                    isActive
                      ? "border-emerald-400/15 bg-emerald-400/[0.08] text-emerald-200"
                      : "border-transparent text-white/48 hover:border-white/[0.06] hover:bg-white/[0.035] hover:text-white/85"
                  }`
                }
                title={collapsed ? item.label : undefined}
              >
                <DashboardIcon name={item.icon} />
                {!collapsed && <span className="text-[13px] font-medium">{item.label}</span>}
              </NavLink>
            ))}
          </nav>

          <div className="space-y-1 border-t border-white/[0.07] pt-3">
            <button
              onClick={onSignOut}
              className={`flex min-h-11 w-full items-center rounded-xl border border-transparent text-white/40 transition hover:border-red-400/10 hover:bg-red-400/[0.05] hover:text-red-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-400 ${
                collapsed ? "justify-center px-2" : "gap-3 px-3"
              }`}
              title={collapsed ? "Выйти" : undefined}
            >
              <DashboardIcon name="logout" />
              {!collapsed && <span className="text-[13px] font-medium">Выйти</span>}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
