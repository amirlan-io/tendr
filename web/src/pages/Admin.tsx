import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { adminApi, ApiError, getApiErrorStatus } from "../clientId";
import {
  clearAdminSession,
  getAdminKey,
  isAdminAuthError,
  setAdminKey,
} from "../security/adminSession";

type Stats = {
  users: { total: number; pilot: number; subscribed: number };
  analyses: {
    total: number;
    incomplete: number;
    with_high_risk: number;
    last_24h: number;
    last_7d: number;
    avg_requirements: number;
  };
  risk_distribution: Record<string, number>;
  top_customers: { customer: string; count: number }[];
  by_day: { date: string; count: number }[];
  generated_at: string;
};

type RecentItem = {
  id: number;
  lot_id: string;
  title: string;
  customer: string;
  overall_risk: string;
  n_requirements: number;
  n_red_flags: number;
  incomplete: boolean;
  created_at: string;
};

const RISK_COLORS: Record<string, string> = {
  low: "#10b981",
  medium: "#f59e0b",
  high: "#ef4444",
  needs_review: "#71717a",
};

const RISK_LABELS: Record<string, string> = {
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
  needs_review: "На проверке",
};

const ADMIN_NOT_CONFIGURED_MSG = "ADMIN_API_KEY не настроен на сервере";

export function AdminPage() {
  const [adminKey, setAdminKeyState] = useState<string | null>(() => getAdminKey());
  const [keyInput, setKeyInput] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [tokenResult, setTokenResult] = useState<{
    status: string;
    message: string;
  } | null>(null);
  const [tokenChecking, setTokenChecking] = useState(false);

  const logout = useCallback(() => {
    clearAdminSession();
    setAdminKeyState(null);
    setStats(null);
    setRecent([]);
    setTokenResult(null);
    setAuthError(null);
    setServerError(null);
    setKeyInput("");
  }, []);

  const handleAuthFailure = useCallback(() => {
    // При 401/403 очищаем административную сессию и снова показываем форму входа.
    clearAdminSession();
    setAdminKeyState(null);
    setStats(null);
    setRecent([]);
    setTokenResult(null);
    setAuthError("Требуется авторизация. Проверьте ключ и войдите снова.");
  }, []);

  const login = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const v = keyInput.trim();
      if (!v) {
        setAuthError("Введите административный ключ.");
        return;
      }
      // Храним только в sessionStorage, никогда в localStorage и console.
      setAdminKey(v);
      setAdminKeyState(v);
      setKeyInput("");
      setAuthError(null);
      setServerError(null);
      setTokenResult(null);
    },
    [keyInput],
  );

  const loadDashboard = useCallback(async () => {
    const key = getAdminKey();
    if (!key) return;
    setLoading(true);
    setServerError(null);
    try {
      const [s, r] = await Promise.all([
        adminApi<Stats>("/api/admin/stats", key),
        adminApi<{ items: RecentItem[] }>("/api/admin/recent", key),
      ]);
      setStats(s);
      setRecent(r.items);
    } catch (e) {
      const status = getApiErrorStatus(e);
      if (isAdminAuthError(status)) {
        handleAuthFailure();
        return;
      }
      if (status === 503) {
        setServerError(ADMIN_NOT_CONFIGURED_MSG);
        return;
      }
      setServerError(
        e instanceof ApiError ? e.message : "Не удалось загрузить статистику. Попробуйте позже.",
      );
    } finally {
      setLoading(false);
    }
  }, [handleAuthFailure]);

  const checkToken = async () => {
    const key = getAdminKey();
    if (!key) {
      handleAuthFailure();
      return;
    }
    setTokenChecking(true);
    setTokenResult(null);
    try {
      const r = await adminApi<{ status: string; message: string }>(
        "/api/admin/token-check",
        key,
      );
      setTokenResult(r);
    } catch (e) {
      const status = getApiErrorStatus(e);
      if (isAdminAuthError(status)) {
        handleAuthFailure();
        return;
      }
      if (status === 503) {
        setTokenResult({ status: "error", message: ADMIN_NOT_CONFIGURED_MSG });
        return;
      }
      setTokenResult({
        status: "error",
        message: e instanceof ApiError ? e.message : "Не удалось проверить токен. Попробуйте позже.",
      });
    } finally {
      setTokenChecking(false);
    }
  };

  // Не загружаем статистику до ввода ключа. Автообновление — только при активной сессии.
  useEffect(() => {
    if (!adminKey) return;
    void loadDashboard();
    const interval = setInterval(() => void loadDashboard(), 30000);
    return () => clearInterval(interval);
  }, [adminKey, loadDashboard]);

  if (!adminKey) {
    return (
      <Layout>
        <div className="max-w-md mx-auto px-6 py-16">
          <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Пилот
          </div>
          <h1 className="text-3xl font-bold tracking-tight mb-2">Дашборд</h1>
          <p className="text-sm text-[var(--text-muted)] mb-6">
            Введите административный ключ для доступа к статистике. Ключ хранится
            только в текущей вкладке и не сохраняется после её закрытия.
          </p>
          <form onSubmit={login} className="space-y-3">
            <label className="block text-sm font-medium" htmlFor="admin-key">
              Административный ключ
            </label>
            <input
              id="admin-key"
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="••••••••"
              autoComplete="off"
              className="w-full px-4 py-2 border border-[var(--border-strong)] bg-[var(--bg-elevated)] text-[var(--text)] rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
            />
            {authError && (
              <div role="alert" className="text-sm" style={{ color: "#ef4444" }}>
                {authError}
              </div>
            )}
            <button
              type="submit"
              className="w-full px-4 py-2.5 rounded-lg font-medium text-white transition"
              style={{ backgroundColor: "var(--accent)" }}
            >
              Войти
            </button>
          </form>
        </div>
      </Layout>
    );
  }

  if (loading && !stats) {
    return (
      <Layout>
        <div className="max-w-6xl mx-auto px-6 py-16">
          <div role="status" aria-busy="true" className="text-[var(--text-muted)]">Загрузка...</div>
        </div>
      </Layout>
    );
  }

  const maxByDay = Math.max(...(stats?.by_day.map((d) => d.count) ?? [1]), 1);
  const maxRisk = Math.max(
    ...Object.values(stats?.risk_distribution ?? {}).map(Number),
    1,
  );

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-6 py-12">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">
              Пилот
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Дашборд</h1>
          </div>
          <div className="flex gap-2">
            <button
              onClick={checkToken}
              className="px-3 py-1.5 rounded-md text-sm font-medium transition"
              style={{
                backgroundColor: "var(--accent)",
                color: "white",
              }}
            >
              {tokenChecking ? "⏳ Проверка..." : "🔑 Проверить токен"}
            </button>
            <button
              onClick={() => void loadDashboard()}
              className="px-3 py-1.5 rounded-md text-sm border transition"
              style={{
                borderColor: "var(--border-strong)",
                color: "var(--text-muted)",
              }}
            >
              ↻ Обновить
            </button>
            <button
              onClick={logout}
              className="px-3 py-1.5 rounded-md text-sm border transition"
              style={{
                borderColor: "var(--border-strong)",
                color: "var(--text-muted)",
              }}
            >
              Выйти
            </button>
          </div>
        </div>

        {serverError && (
          <div
            role="alert"
            className="rounded-xl p-4 mb-6 border"
            style={{
              backgroundColor: "var(--bg-elevated)",
              borderColor: "#ef4444",
              borderLeftWidth: "3px",
            }}
          >
            <div className="font-semibold mb-1" style={{ color: "#ef4444" }}>
              Ошибка загрузки
            </div>
            <div className="text-sm text-[var(--text-muted)]">{serverError}</div>
          </div>
        )}

        {/* Результат проверки токена */}
        {tokenResult && (
          <div
            className="rounded-xl p-4 mb-6 border"
            style={{
              backgroundColor: "var(--bg-elevated)",
              borderColor:
                tokenResult.status === "ok"
                  ? "#10b981"
                  : tokenResult.status === "no_token"
                    ? "#f59e0b"
                    : "#ef4444",
              borderLeftWidth: "3px",
            }}
          >
            <div className="flex items-start gap-3">
              <div
                className="text-2xl"
                style={{
                  color:
                    tokenResult.status === "ok"
                      ? "#10b981"
                      : tokenResult.status === "no_token"
                        ? "#f59e0b"
                        : "#ef4444",
                }}
              >
                {tokenResult.status === "ok"
                  ? "✓"
                  : tokenResult.status === "no_token"
                    ? "⚠"
                    : "✗"}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold mb-1">
                  Токен goszakup.gov.kz: {tokenResult.status}
                </div>
                <div className="text-sm text-[var(--text-muted)]">
                  {tokenResult.message}
                </div>
              </div>
            </div>
          </div>
        )}

        {stats && (
          <>
            {/* KPI cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <Kpi
                label="Пользователей"
                value={stats.users.total}
                sub={`${stats.users.pilot} пилот`}
              />
              <Kpi
                label="Анализов всего"
                value={stats.analyses.total}
                sub={`${stats.analyses.last_24h} за 24ч`}
              />
              <Kpi
                label="High risk"
                value={stats.analyses.with_high_risk}
                sub={`${Math.round(
                  (stats.analyses.with_high_risk /
                    Math.max(stats.analyses.total, 1)) *
                    100,
                )}% от всех`}
                color="#ef4444"
              />
              <Kpi
                label="Среднее требований"
                value={stats.analyses.avg_requirements}
                sub="на лот"
                color="#10b981"
              />
            </div>

            {/* График по дням */}
            <section
              className="rounded-xl border p-6 mb-6"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <h2 className="text-lg font-semibold mb-1">Активность за 14 дней</h2>
              <p className="text-sm text-[var(--text-muted)] mb-4">
                Количество анализов по дням
              </p>
              {stats.by_day.length === 0 ? (
                <div className="text-sm text-[var(--text-subtle)] py-8 text-center">
                  Пока нет данных. Проведите первый анализ.
                </div>
              ) : (
                <div className="flex items-end gap-1.5 h-40">
                  {stats.by_day.map((d) => {
                    const heightPct = (d.count / maxByDay) * 100;
                    return (
                      <div
                        key={d.date}
                        className="flex-1 flex flex-col items-center gap-1.5"
                      >
                        <div className="text-[10px] text-[var(--text-muted)] tabular-nums">
                          {d.count}
                        </div>
                        <div
                          className="w-full rounded-t transition-all"
                          style={{
                            height: `${heightPct}%`,
                            backgroundColor: "var(--accent)",
                            minHeight: d.count > 0 ? "4px" : "0",
                          }}
                        />
                        <div className="text-[10px] text-[var(--text-subtle)] tabular-nums">
                          {d.date.slice(5)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
              {/* Распределение рисков */}
              <section
                className="rounded-xl border p-6"
                style={{
                  backgroundColor: "var(--bg-elevated)",
                  borderColor: "var(--border)",
                }}
              >
                <h2 className="text-lg font-semibold mb-1">Распределение рисков</h2>
                <p className="text-sm text-[var(--text-muted)] mb-4">
                  По результатам Legal Agent
                </p>
                <div className="space-y-3">
                  {Object.entries(stats.risk_distribution).map(([risk, count]) => {
                    const pct = (count / maxRisk) * 100;
                    return (
                      <div key={risk}>
                        <div className="flex justify-between text-sm mb-1">
                          <span style={{ color: RISK_COLORS[risk] }}>
                            {RISK_LABELS[risk]}
                          </span>
                          <span className="text-[var(--text-muted)] tabular-nums">
                            {count}
                          </span>
                        </div>
                        <div
                          className="h-2 rounded-full overflow-hidden"
                          style={{ backgroundColor: "var(--border)" }}
                        >
                          <div
                            className="h-full transition-all"
                            style={{
                              width: `${pct}%`,
                              backgroundColor: RISK_COLORS[risk],
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              {/* Топ заказчиков */}
              <section
                className="rounded-xl border p-6"
                style={{
                  backgroundColor: "var(--bg-elevated)",
                  borderColor: "var(--border)",
                }}
              >
                <h2 className="text-lg font-semibold mb-1">Топ заказчиков</h2>
                <p className="text-sm text-[var(--text-muted)] mb-4">
                  Чаще всего анализируются
                </p>
                {stats.top_customers.length === 0 ? (
                  <div className="text-sm text-[var(--text-subtle)] py-8 text-center">
                    Пока нет данных
                  </div>
                ) : (
                  <div className="space-y-2">
                    {stats.top_customers.map((c, i) => (
                      <div
                        key={c.customer}
                        className="flex items-center gap-3 px-3 py-2 rounded-lg"
                        style={{ backgroundColor: "var(--bg)" }}
                      >
                        <div
                          className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold"
                          style={{
                            backgroundColor: "var(--accent-glow)",
                            color: "var(--accent)",
                          }}
                        >
                          {i + 1}
                        </div>
                        <div className="flex-1 truncate text-sm">{c.customer}</div>
                        <div className="text-sm text-[var(--text-muted)] tabular-nums">
                          {c.count}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>

            {/* Live-лента */}
            <section
              className="rounded-xl border p-6"
              style={{
                backgroundColor: "var(--bg-elevated)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-lg font-semibold mb-1">Последние анализы</h2>
                  <p className="text-sm text-[var(--text-muted)]">
                    Обновляется в реальном времени
                  </p>
                </div>
                <span
                  className="w-2 h-2 rounded-full animate-pulse"
                  style={{ backgroundColor: "var(--accent)" }}
                />
              </div>
              {recent.length === 0 ? (
                <div className="text-sm text-[var(--text-subtle)] py-8 text-center">
                  Пока нет анализов
                </div>
              ) : (
                <div className="space-y-1.5">
                  {recent.map((r) => (
                    <div
                      key={r.id}
                      className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm"
                      style={{ backgroundColor: "var(--bg)" }}
                    >
                      <span
                        className="px-2 py-0.5 rounded text-xs font-medium"
                        style={{
                          backgroundColor: r.incomplete
                            ? "rgba(245, 158, 11, 0.15)"
                            : `${RISK_COLORS[r.overall_risk]}20`,
                          color: r.incomplete
                            ? "#f59e0b"
                            : RISK_COLORS[r.overall_risk],
                        }}
                      >
                        {r.incomplete ? "?" : RISK_LABELS[r.overall_risk]}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="truncate font-medium">
                          {r.title || `Лот ${r.lot_id}`}
                        </div>
                        <div className="text-xs text-[var(--text-muted)] truncate">
                          {r.customer}
                        </div>
                      </div>
                      <Link
                        to={`/analyze?re=${r.lot_id}`}
                        className="text-xs px-2 py-1 rounded-md transition"
                        style={{ color: "var(--accent)" }}
                      >
                        Открыть
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <div className="mt-8 text-center text-xs text-[var(--text-subtle)]">
              Обновлено: {new Date(stats.generated_at).toLocaleString("ru-RU")}
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}

function Kpi({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: number;
  sub?: string;
  color?: string;
}) {
  return (
    <div
      className="rounded-xl border p-5"
      style={{
        backgroundColor: "var(--bg-elevated)",
        borderColor: "var(--border)",
      }}
    >
      <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2">
        {label}
      </div>
      <div
        className="text-3xl font-bold tracking-tight tabular-nums"
        style={{ color: color || "var(--text)" }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-xs text-[var(--text-muted)] mt-1">{sub}</div>
      )}
    </div>
  );
}
