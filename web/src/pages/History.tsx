import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Layout } from "../Layout";
import { useT } from "../i18n";
import { api } from "../clientId";

const HISTORY_KEY = "tendr_history";

type LocalItem = {
  lot_id: string;
  title: string;
  customer: string;
  method: string;
  overall_risk?: string;
  n_requirements: number;
  n_red_flags: number;
  created_at: string;
};

type ServerItem = LocalItem;

function loadLocal(): LocalItem[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveLocal(items: LocalItem[]) {
  window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 20)));
}

export function HistoryPage() {
  const t = useT();
  const [items, setItems] = useState<LocalItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLocal();
    api<{ items: ServerItem[] }>("/api/lots/history")
      .then((r) => {
        const merged = mergeWithLocal(r.items || []);
        setItems(merged);
        saveLocal(merged);
      })
      .catch(() => setItems(loadLocal()))
      .finally(() => setLoading(false));
  }, []);

  function clear() {
    if (!confirm("?")) return;
    setItems([]);
    saveLocal([]);
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-6 py-8">
        <Link to="/" className="text-sm text-[var(--text-muted)] hover:underline">
          {t("common.back")}
        </Link>
        <div className="flex items-center justify-between mt-2 mb-6">
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

        {loading ? (
          <div className="text-[var(--text-muted)] text-sm">…</div>
        ) : items.length === 0 ? (
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

function mergeWithLocal(server: ServerItem[]): LocalItem[] {
  const local = loadLocal();
  const seen = new Set<string>();
  const merged: LocalItem[] = [];
  // Серверные свежее (созданы на бэке, time идёт с UTC сервера)
  for (const s of server) {
    const key = s.lot_id + s.created_at;
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(s);
    }
  }
  // Добавляем локальные, которых нет на сервере
  for (const l of local) {
    const key = l.lot_id + l.created_at;
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(l);
    }
  }
  return merged.slice(0, 20);
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
          <div className="text-xs text-[var(--text-muted)] dark:text-slate-400 dark:text-slate-400 mt-0.5">
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
