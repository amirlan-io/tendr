import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { DashboardSidebar } from "./DashboardSidebar";
import { DashboardHeader } from "./DashboardHeader";
import { DashboardIcon } from "./DashboardIcon";
import { DashboardMobileNav } from "./DashboardMobileNav";
import { EmbedProvider } from "./Embedded";
import { DASHBOARD_NAV } from "./dashboard.data";
import { AssistantDock } from "./components/AssistantDock";
import { useModalFocus } from "../hooks/useModalFocus";

function displayNameOf(email: string | null, metaName: unknown): string {
  if (typeof metaName === "string" && metaName.trim()) return metaName.trim();
  if (email) return email.split("@")[0];
  return "пользователь";
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name.trim()[0] || "T").toUpperCase();
}

export function DashboardLayout() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchDialogRef = useModalFocus<HTMLElement>(searchOpen, () => setSearchOpen(false));

  const email = user?.email ?? null;
  const metaName = (user?.user_metadata as Record<string, unknown> | undefined)?.["full_name"];
  const displayName = displayNameOf(email, metaName);
  const initials = initialsOf(displayName);
  const tariffLabel = user ? "Пробный доступ" : "";

  const active = DASHBOARD_NAV.find(
    (item) =>
      item.to !== "/dashboard" && location.pathname.startsWith(item.to),
  );
  const currentLabel = active?.label ?? "Обзор";

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === "Escape") {
        setMobileOpen(false);
        setSearchOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    setMobileOpen(false);
    setSearchOpen(false);
    setQuery("");
  }, [location.pathname]);

  const searchResults = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    if (!normalized) return DASHBOARD_NAV;
    return DASHBOARD_NAV.filter((item) =>
      `${item.label} ${item.description}`.toLocaleLowerCase("ru").includes(normalized),
    );
  }, [query]);

  const confirmSignOut = async () => {
    if (!window.confirm("Выйти из личного кабинета?")) return;
    await signOut();
    navigate("/", { replace: true });
  };

  return (
    <div className="dashboard-shell relative min-h-screen overflow-x-clip bg-[#0a0a0b] text-[#f3f3f3]">
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_78%_3%,rgba(255,255,255,.035),transparent_26%),linear-gradient(135deg,rgba(255,255,255,.012),transparent_40%)]"
      />
      <DashboardSidebar
        email={email}
        displayName={displayName}
        initials={initials}
        tariffLabel={tariffLabel}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
        onOpenSearch={() => setSearchOpen(true)}
        onSignOut={() => void confirmSignOut()}
      />
      <div
        className={`relative min-h-screen transition-[padding] duration-300 ${
          collapsed ? "lg:pl-[72px]" : "lg:pl-[248px]"
        }`}
      >
        <DashboardHeader
          title={currentLabel}
          breadcrumb={["Tendr", currentLabel]}
          initials={initials}
          onOpenMobile={() => setMobileOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
          onToggleCollapse={() => setCollapsed((v) => !v)}
          collapsed={collapsed}
        />
        <main className="mx-auto w-full max-w-[1440px] px-4 pb-24 pt-7 sm:px-7 sm:pb-12 sm:pt-9">
          <EmbedProvider>
            <Outlet />
          </EmbedProvider>
        </main>
      </div>
      <DashboardMobileNav />
      <AssistantDock />

      {searchOpen && (
        <div
          className="fixed inset-0 z-[70] flex items-start justify-center bg-black/75 px-4 pt-[12vh] backdrop-blur-sm"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setSearchOpen(false);
          }}
        >
          <section
            ref={searchDialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Поиск по кабинету"
            className="w-full max-w-[560px] overflow-hidden rounded-xl border border-white/[0.09] bg-[#151516] shadow-[0_24px_80px_rgba(0,0,0,.65)]"
          >
            <div className="flex items-center gap-3 border-b border-white/[0.07] px-4">
              <Search aria-hidden className="h-[17px] w-[17px] shrink-0 text-white/32" strokeWidth={1.6} />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && searchResults[0]) {
                    navigate(searchResults[0].to);
                    setSearchOpen(false);
                  }
                }}
                placeholder="Найти раздел или действие..."
                className="h-14 min-w-0 flex-1 bg-transparent text-sm text-white/90 outline-none placeholder:text-white/25"
              />
              <button
                type="button"
                aria-label="Закрыть поиск"
                onClick={() => setSearchOpen(false)}
                className="flex h-11 w-11 items-center justify-center rounded-md text-white/55 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300"
              >
                <X aria-hidden className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[430px] overflow-y-auto p-2">
              <p className="px-2 pb-2 pt-1 text-[11px] font-medium uppercase tracking-[.14em] text-white/50">
                Разделы кабинета
              </p>
              {searchResults.length > 0 ? (
                <div className="space-y-1">
                  {searchResults.map((item) => (
                    <Link
                      key={item.to}
                      to={item.to}
                      onClick={() => setSearchOpen(false)}
                      className="group flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-white/[0.06] focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60"
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/[0.07] bg-white/[0.025] text-white/42 group-hover:text-white/75">
                        <DashboardIcon name={item.icon} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[12px] font-medium text-white/80">{item.label}</span>
                        <span className="mt-0.5 block truncate text-xs text-white/55">{item.description}</span>
                      </span>
                      <ArrowUpRight aria-hidden className="h-3.5 w-3.5 text-white/18 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-white/55" />
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="px-3 py-10 text-center text-xs text-white/32">
                  Ничего не найдено. Попробуйте другой запрос.
                </div>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-white/[0.06] px-4 py-2.5 text-[11px] text-white/50">
              <span>Enter — перейти</span>
              <span>Esc — закрыть</span>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
