import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { LayoutOrEmbed } from "../dashboard/Embedded";
import { useT } from "../i18n";
import { clearHistory, type HistoryItem as LocalItem } from "../historyStore";
import { useHistoryList } from "../dashboard/hooks/useDashboardData";
import { LotSourceLink } from "../dashboard/components/LotSourceLink";

export function HistoryPage({ embedded = false }: { embedded?: boolean } = {}) {
  const t = useT();
  const { items, total, loading, loadingMore, offline, error, hasMore, loadMore, reload } =
    useHistoryList();
  const [query, setQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("all");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = items.filter((it) => {
      if (riskFilter !== "all" && (it.overall_risk || "needs_review") !== riskFilter) return false;
      if (!q) return true;
      return `${it.title} ${it.customer} ${it.lot_id}`.toLowerCase().includes(q);
    });
    return [...filtered].sort((a, b) =>
      sortDir === "desc"
        ? b.created_at.localeCompare(a.created_at)
        : a.created_at.localeCompare(b.created_at),
    );
  }, [items, query, riskFilter, sortDir]);

  function clear() {
    if (!window.confirm("Очистить локальную копию истории в этом браузере? Серверные записи останутся.")) return;
    clearHistory();
    void reload();
  }

  return (
    <LayoutOrEmbed embedded={embedded}>
      <div className="max-w-4xl mx-auto px-6 py-8">
        <Link to={embedded ? "/dashboard" : "/"} className="text-sm text-[var(--text-muted)] hover:underline">
          {t("common.back")}
        </Link>
        <div className="flex items-center justify-between mt-2 mb-4">
          <h1 className="text-2xl font-bold">{t("history.title")}</h1>
          {items.length > 0 && (
            <button
              onClick={clear}
              className="text-sm text-[var(--accent)] hover:underline"
            >
              {t("history.clear")}
            </button>
          )}
        </div>

        <p className="text-xs text-[var(--text-muted)] mb-4">
          {offline
            ? "Сервер недоступен: показана локальная копия с этого устройства, без утверждений о синхронизации."
            : "История загружается с сервера вашего аккаунта; локальная копия хранится в этом браузере как offline-запас."}
          {total !== null && ` Всего записей: ${total}.`}
        </p>

        {error && (
          <p role="alert" className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </p>
        )}

        <div className="mb-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по названию, заказчику или номеру"
            aria-label="Поиск по истории"
            className="px-3 py-2 border rounded dark:bg-slate-700 text-sm"
          />
          <select
            value={riskFilter}
            onChange={(e) => setRiskFilter(e.target.value)}
            aria-label="Фильтр по статусу риска"
            className="px-3 py-2 border rounded dark:bg-slate-700 text-sm"
          >
            <option value="all">Все статусы</option>
            <option value="high">Высокий риск</option>
            <option value="medium">Средний риск</option>
            <option value="low">Низкий риск</option>
            <option value="needs_review">На проверке</option>
          </select>
          <button
            type="button"
            onClick={() => setSortDir((d) => (d === "desc" ? "asc" : "desc"))}
            aria-label={sortDir === "desc" ? "Сортировать от старых к новым" : "Сортировать от новых к старым"}
            className="px-3 py-2 border rounded dark:bg-slate-700 text-sm"
          >
            {sortDir === "desc" ? "Новые ↓" : "Старые ↑"}
          </button>
        </div>

        {loading ? (
          <div role="status" aria-busy="true" className="text-[var(--text-muted)] text-sm">Загрузка истории…</div>
        ) : visible.length === 0 ? (
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-8 text-center text-slate-500">
            {items.length === 0 ? t("history.empty") : "Ничего не найдено. Измените поиск или фильтр."}
          </div>
        ) : (
          <div className="space-y-3">
            {visible.map((it) => (
              <HistoryCard key={it.lot_id + it.created_at} item={it} embedded={embedded} />
            ))}
          </div>
        )}

        {hasMore && (
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="mt-4 w-full px-4 py-2.5 border rounded-lg text-sm hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
          >
            {loadingMore ? "Загрузка…" : "Показать ещё"}
          </button>
        )}
      </div>
    </LayoutOrEmbed>
  );
}

function HistoryCard({ item, embedded }: { item: LocalItem; embedded: boolean }) {
  const t = useT();
  const risk = item.overall_risk || "needs_review";
  const riskColor =
    risk === "high"
      ? "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-200"
      : risk === "medium"
        ? "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-200"
        : "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-200";

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 hover:shadow-sm transition">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-[var(--text)] truncate">
            {item.title}
          </div>
          <div className="text-xs text-[var(--text-muted)] dark:text-slate-400 mt-0.5">
            {item.customer} · № {item.lot_id}
          </div>
          <div className="flex gap-3 mt-2 text-xs text-[var(--text-muted)] dark:text-slate-400">
            <span>Требований: {item.n_requirements}</span>
            <span>Рисков: {item.n_red_flags}</span>
            <span>{item.created_at ? new Date(item.created_at).toLocaleString() : "—"}</span>
          </div>
          {item.url && (
            <Link
              to={`${embedded ? "/dashboard" : ""}/analyze?lot_url=${encodeURIComponent(item.url)}`}
              className="mt-2 mr-3 inline-block text-xs font-medium"
              style={{ color: "var(--accent)" }}
            >
              Открыть анализ →
            </Link>
          )}
          <LotSourceLink
            sourceUrl={item.url}
            lotId={item.lot_id}
            label="Лот на Госзакупках ↗"
            className="mt-2 inline-block text-xs font-medium"
          />
        </div>
        <div
          className={`text-xs px-2 py-1 rounded-full whitespace-nowrap ${riskColor}`}
        >
          {risk}
        </div>
      </div>
    </div>
  );
}
