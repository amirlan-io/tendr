import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { useT } from "../i18n";
import {
  clearHistory,
  loadHistory,
  type HistoryItem as LocalItem,
} from "../historyStore";

export function HistoryPage() {
  const t = useT();
  const [items, setItems] = useState<LocalItem[]>([]);

  // Серверного endpoint /api/lots/history в backend нет, поэтому история
  // честно ведётся только локально. Никаких «тихих» ошибок: запроса нет вовсе.
  useEffect(() => {
    setItems(loadHistory());
  }, []);

  function clear() {
    if (!window.confirm("Очистить историю проверок в этом браузере?")) return;
    clearHistory();
    setItems([]);
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-6 py-8">
        <Link to="/" className="text-sm text-[var(--text-muted)] hover:underline">
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

        <p className="text-xs text-[var(--text-muted)] mb-6">
          История хранится только в этом браузере и содержит названия лотов и
          заказчиков. На общем компьютере очистите её после работы — данные
          останутся здесь и после закрытия вкладки.
        </p>

        {items.length === 0 ? (
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-8 text-center text-slate-500">
            {t("history.empty")}
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((it) => (
              <HistoryCard key={it.lot_id + it.created_at} item={it} />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}

function HistoryCard({ item }: { item: LocalItem }) {
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
            <span>📋 {item.n_requirements}</span>
            <span>⚠️ {item.n_red_flags}</span>
            <span>{new Date(item.created_at).toLocaleString()}</span>
          </div>
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
