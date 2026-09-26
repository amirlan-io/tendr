import { Link } from "react-router-dom";
import { useLang, useT } from "./i18n";
import { useTheme } from "./theme";
import { useAuth } from "./auth/AuthContext";

export function Layout({ children }: { children: React.ReactNode }) {
  const t = useT();
  const [lang, setLang] = useLang();
  const [theme, setTheme] = useTheme();
  const { user, loading, signOut } = useAuth();

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header
        className="sticky top-0 z-50 border-b backdrop-blur-md"
        style={{
          backgroundColor: "color-mix(in srgb, var(--bg) 80%, transparent)",
          borderColor: "var(--border)",
        }}
      >
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
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

          <nav className="flex items-center gap-1">
            <NavLink to="/analyze">{t("home.nav.analyze")}</NavLink>
            <NavLink to="/history">{t("home.nav.history")}</NavLink>
            <NavLink to="/b2g">B2G</NavLink>
            <NavLink to="/lots">📋 Лоты</NavLink>
            <NavLink to="/admin">📊</NavLink>
            <a
              href="https://t.me/TendrBot"
              target="_blank"
              rel="noreferrer"
              className="px-3 py-1.5 text-sm rounded-md text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--accent-glow)] transition"
            >
              {t("home.nav.bot")}
            </a>

            <div className="w-px h-5 bg-[var(--border-strong)] mx-2" />

            <div className="flex gap-0.5 p-0.5 rounded-md bg-[var(--border)]">
              <LangBtn current={lang} target="ru" onClick={() => setLang("ru")}>
                RU
              </LangBtn>
              <LangBtn current={lang} target="kk" onClick={() => setLang("kk")}>
                KK
              </LangBtn>
            </div>

            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
              className="ml-1 w-8 h-8 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--accent-glow)] transition"
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>

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
                    className="hidden rounded-lg px-3 py-2 text-sm text-[var(--text-muted)] transition hover:bg-[var(--accent-glow)] hover:text-[var(--text)] sm:block"
                  >
                    Выйти
                  </button>
                </div>
              ) : (
                <Link
                  to="/login"
                  className="ml-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-400"
                >
                  Войти
                </Link>
              ))}
          </nav>
        </div>
      </header>

      <main>{children}</main>

      <footer
        className="border-t mt-24"
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
  return (
    <Link
      to={to}
      className="px-3 py-1.5 text-sm rounded-md text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--accent-glow)] transition"
    >
      {children}
    </Link>
  );
}

function LangBtn({
  current,
  target,
  onClick,
  children,
}: {
  current: string;
  target: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  const active = current === target;
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 text-xs rounded font-medium transition ${
        active
          ? "bg-[var(--bg-elevated)] text-[var(--text)] shadow-sm"
          : "text-[var(--text-muted)] hover:text-[var(--text)]"
      }`}
    >
      {children}
    </button>
  );
}
