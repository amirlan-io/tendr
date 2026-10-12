import { ChevronRight, Search } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { DASHBOARD_NAV } from "./dashboard.data";
import { DashboardIcon } from "./DashboardIcon";
import type { NavItem } from "./dashboard.types";

type Props = {
  email: string | null;
  displayName: string;
  initials: string;
  tariffLabel: string;
  collapsed: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onOpenSearch: () => void;
  onSignOut: () => void;
};

// Группы заданы маршрутами, а не индексами: добавление нового пункта
// в DASHBOARD_NAV не должно молча сдвигать остальные разделы.
const NAV_BY_ROUTE = new Map(DASHBOARD_NAV.map((item) => [item.to, item]));

function navByRoute(...routes: string[]): NavItem[] {
  return routes.map((route) => NAV_BY_ROUTE.get(route)).filter((item): item is NavItem => Boolean(item));
}

const PRIMARY_NAV = navByRoute("/dashboard", "/dashboard/analyze", "/dashboard/lots");
const WORKSPACE_NAV = navByRoute(
  "/dashboard/suppliers",
  "/dashboard/history",
  "/dashboard/documents",
  "/dashboard/b2g",
);
const BILLING_NAV = navByRoute("/dashboard/billing");
const SETTINGS_ITEM = NAV_BY_ROUTE.get("/dashboard/settings");

function NavigationGroup({
  label,
  items,
  collapsed,
  onNavigate,
}: {
  label?: string;
  items: NavItem[];
  collapsed: boolean;
  onNavigate: () => void;
}) {
  return (
    <div className="space-y-0.5">
      {label && (
        <p
          className={`mb-1.5 px-2.5 text-[10px] font-medium uppercase tracking-[.12em] text-white/25 ${
            collapsed ? "lg:hidden" : ""
          }`}
        >
          {label}
        </p>
      )}
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/dashboard"}
          aria-label={collapsed ? item.label : undefined}
          onClick={onNavigate}
          title={collapsed ? item.label : undefined}
          className={({ isActive }) =>
            `group flex min-h-10 items-center gap-2.5 rounded-[7px] px-2.5 text-[13px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60 ${
              isActive
                ? "bg-white/[0.09] font-medium text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,.035)]"
                : "text-white/48 hover:bg-white/[0.045] hover:text-white/85"
            } ${collapsed ? "lg:justify-center lg:px-2" : ""}`
          }
        >
          <span className="shrink-0 text-white/45 transition-colors group-hover:text-white/75">
            <DashboardIcon name={item.icon} />
          </span>
          <span className={`truncate ${collapsed ? "lg:hidden" : ""}`}>{item.label}</span>
        </NavLink>
      ))}
    </div>
  );
}

export function DashboardSidebar({
  email,
  displayName,
  initials,
  tariffLabel,
  collapsed,
  mobileOpen,
  onCloseMobile,
  onOpenSearch,
  onSignOut,
}: Props) {
  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Закрыть меню"
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
          onClick={onCloseMobile}
        />
      )}

      <aside
        aria-label="Навигация кабинета"
        className={`fixed inset-y-0 left-0 z-50 flex w-[260px] border-r border-white/[0.065] bg-[#111112] transition-[width,transform] duration-300 ${
          collapsed ? "lg:w-[72px]" : "lg:w-[248px]"
        } ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}
      >
        <div className="flex min-w-0 flex-1 flex-col p-3">
          <Link
            to="/dashboard"
            onClick={onCloseMobile}
            className={`group flex min-h-12 items-center gap-3 rounded-lg px-2 transition-colors hover:bg-white/[0.035] ${
              collapsed ? "lg:justify-center lg:px-1" : ""
            }`}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[7px] bg-[#f2f2f2] text-xs font-bold text-[#111112] shadow-[0_1px_0_rgba(255,255,255,.16)]">
              T
            </span>
            <span className={`min-w-0 flex-1 ${collapsed ? "lg:hidden" : ""}`}>
              <span className="block truncate text-[13px] font-semibold text-white/90">Tendr</span>
              <span className="mt-0.5 block truncate text-[10px] text-white/32">{tariffLabel}</span>
            </span>
            <ChevronRight
              aria-hidden
              className={`h-3.5 w-3.5 shrink-0 text-white/20 transition-transform group-hover:translate-x-0.5 group-hover:text-white/45 ${
                collapsed ? "lg:hidden" : ""
              }`}
              strokeWidth={1.6}
            />
          </Link>

          <button
            type="button"
            onClick={onOpenSearch}
            className={`mt-4 flex min-h-10 w-full items-center gap-2.5 rounded-[7px] px-2.5 text-[13px] text-white/48 transition-colors hover:bg-white/[0.045] hover:text-white/85 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60 ${
              collapsed ? "lg:justify-center lg:px-2" : ""
            }`}
            title={collapsed ? "Поиск" : undefined}
          >
            <Search aria-hidden className="h-[17px] w-[17px] shrink-0" strokeWidth={1.55} />
            <span className={`flex-1 text-left ${collapsed ? "lg:hidden" : ""}`}>Поиск</span>
            <kbd
              className={`rounded border border-white/[0.07] bg-black/25 px-1.5 py-0.5 font-mono text-[9px] text-white/25 ${
                collapsed ? "lg:hidden" : ""
              }`}
            >
              Ctrl K
            </kbd>
          </button>

          <nav className="mt-2 flex-1 space-y-5 overflow-y-auto py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="Разделы кабинета">
            <NavigationGroup items={PRIMARY_NAV} collapsed={collapsed} onNavigate={onCloseMobile} />
            <NavigationGroup label="Работа" items={WORKSPACE_NAV} collapsed={collapsed} onNavigate={onCloseMobile} />
            <NavigationGroup label="Управление" items={BILLING_NAV} collapsed={collapsed} onNavigate={onCloseMobile} />
          </nav>

          <div className="border-t border-white/[0.06] pt-3">
            <Link
              to="/dashboard/settings"
              onClick={onCloseMobile}
              className={`mb-2 flex items-center gap-2.5 rounded-[7px] px-2 py-2 transition-colors hover:bg-white/[0.045] ${
                collapsed ? "lg:justify-center" : ""
              }`}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/[0.08] bg-white/[0.045] text-[10px] font-semibold text-white/75">
                {initials}
              </span>
              <span className={`min-w-0 flex-1 ${collapsed ? "lg:hidden" : ""}`}>
                <span className="block truncate text-[11px] font-medium text-white/75">{displayName}</span>
                <span className="mt-0.5 block truncate text-[10px] text-white/28">{email ?? ""}</span>
              </span>
            </Link>

            {SETTINGS_ITEM && (
              <NavigationGroup items={[SETTINGS_ITEM]} collapsed={collapsed} onNavigate={onCloseMobile} />
            )}
            <button
              type="button"
              onClick={onSignOut}
              title={collapsed ? "Выйти" : undefined}
              className={`mt-0.5 flex min-h-10 w-full items-center gap-2.5 rounded-[7px] px-2.5 text-[13px] text-white/38 transition-colors hover:bg-white/[0.045] hover:text-white/75 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60 ${
                collapsed ? "lg:justify-center lg:px-2" : ""
              }`}
            >
              <DashboardIcon name="logout" />
              <span className={collapsed ? "lg:hidden" : ""}>Выйти</span>
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
