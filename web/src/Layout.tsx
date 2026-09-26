import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useT } from "./i18n";
import { useAuth } from "./auth/AuthContext";
import { LavaBackground } from "./components/LavaBackground";

export function Layout({ children }: { children: React.ReactNode }) {
  const t = useT();
  const { user, loading, signOut } = useAuth();
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (pathname !== "/" || !hash) return;
    const frame = requestAnimationFrame(() => {
      document.getElementById(hash.slice(1))?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname, hash]);

  return (
    <div className="site-shell min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <LavaBackground />
      <header
        className="sticky top-0 z-50 border-b backdrop-blur-md"
        style={{
          backgroundColor: "color-mix(in srgb, var(--bg) 80%, transparent)",
          borderColor: "var(--border)",
        }}
      >
        <div className="max-w-6xl mx-auto px-4 sm:px-6 grid grid-cols-[1fr_auto] lg:grid-cols-[1fr_auto_1fr] items-center gap-x-3 gap-y-3 py-3 lg:h-20 lg:py-0">
          <Link to="/" className="flex items-center gap-2.5 group">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-white text-sm transition-transform group-hover:scale-105"
              style={{
                background: "linear-gradient(135deg, #10b981 0%, #059669 100%)",
                boxShadow:
                  "0 0 0 1px rgba(16, 185, 129, 0.3), 0 4px 12px -2px rgba(16, 185, 129, 0.4)",
              }}
            >
              T
            </div>
            <span className="text-base font-semibold tracking-tight">
              Tendr
            </span>
          </Link>

          <nav aria-label="Основная навигация" className="row-start-2 col-span-2 flex items-center justify-center gap-1 lg:row-start-1 lg:col-start-2 lg:col-span-1">
            {user ? (
              <>
                <NavLink to="/analyze">AI-ассистент</NavLink>
                <NavLink to="/history">Мои закупки</NavLink>
                <NavLink to="/b2g">Документы</NavLink>
              </>
            ) : (
              <>
                <NavLink to="/#how-it-works">Как работает</NavLink>
                <NavLink to="/#features">Возможности</NavLink>
                <NavLink to="/#pricing">Тарифы</NavLink>
              </>
            )}
          </nav>
          <div className="row-start-1 col-start-2 lg:col-start-3 flex items-center justify-end gap-1 sm:gap-2 min-h-10">
            {!loading &&
              (user ? (
                <div className="ml-2 flex items-center gap-2">
                  <div
                    title={user.email || "Аккаунт"}
                    className="flex h-8 w-8 items-center justify-center rounded-full border border-emerald-500/30 bg-emerald-500/10 text-xs font-semibold text-emerald-500"
                  >
                    {(user.email?.[0] || "T").toUpperCase()}
                  </div>
                  <button
                    onClick={() => void signOut()}
                    className="rounded-lg px-3 py-2 text-sm text-[var(--text-muted)] transition hover:bg-[var(--accent-glow)] hover:text-[var(--text)]"
                  >
                    Выйти
                  </button>
                </div>
              ) : (
                <>
                <Link
                  to="/login"
                  className="rounded-lg px-2 sm:px-3 py-2 text-xs sm:text-sm font-medium text-[var(--text-muted)] transition hover:text-white hover:bg-[var(--accent-glow)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
                >
                  Войти
                </Link>
                <Link
                  to="/login?mode=register"
                  className="whitespace-nowrap rounded-lg bg-emerald-500 px-3 sm:px-4 py-2.5 text-xs sm:text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-emerald-400"
                >
                  Начать бесплатно
                </Link>
                </>
              ))}
          </div>
        </div>
      </header>

      <main className="relative">{children}</main>

      <footer
        className="relative border-t mt-24"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="max-w-6xl mx-auto px-6 py-8 text-center text-xs text-[var(--text-subtle)]">
          {t("common.powered_by")} · 2026
        </div>
      </footer>
    </div>
  );
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const { pathname, hash } = useLocation();
  const active = to === `${pathname}${hash}`;
  return (
    <Link
      to={to}
      aria-current={active ? (hash ? "location" : "page") : undefined}
      className={`whitespace-nowrap px-2 sm:px-3 py-2 text-xs sm:text-sm rounded-lg hover:text-[var(--text)] hover:bg-[var(--accent-glow)] transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${active ? "text-emerald-400 bg-emerald-500/10" : "text-[var(--text-muted)]"}`}
    >
      {children}
    </Link>
  );
}
