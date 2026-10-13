import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../clientId";
import {
  loadHistory,
  saveHistory,
  type HistoryItem,
} from "../../historyStore";
import { hydrateCabinetFromServer, loadDocuments, loadSavedLots } from "../dashboard.data";
import type { PreparedDocument, QuotaInfo, SavedLot } from "../dashboard.types";

type ServerHistory = {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
};

const SAFE_HISTORY_ERROR = "Не удалось загрузить историю с сервера. Показана локальная копия.";

function toQuota(raw: unknown): QuotaInfo | null {
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const limit = o["window_limit"] ?? o["limit"];
  const used = o["used_last_5_hours"] ?? o["used"];
  if (typeof limit !== "number" || typeof used !== "number") return null;
  return {
    limit,
    used,
    isPilot: o["is_pilot"] === true,
    plan: typeof o["plan"] === "string" ? o["plan"] : "free",
    windowHours: typeof o["window_hours"] === "number" ? o["window_hours"] : 5,
    windowLimit: typeof o["window_limit"] === "number" ? o["window_limit"] : 3,
    usedInWindow: typeof o["used_last_5_hours"] === "number" ? o["used_last_5_hours"] : 0,
    remainingInWindow: typeof o["remaining_last_5_hours"] === "number" ? o["remaining_last_5_hours"] : 0,
    windowResetsAt: typeof o["window_resets_at"] === "string" ? o["window_resets_at"] : null,
    reserved: typeof o["reserved_last_5_hours"] === "number" ? o["reserved_last_5_hours"] : 0,
  };
}

/**
 * Серверная история с честным offline-fallback:
 * primary — GET /api/lots/history, при ошибке — локальная копия
 * с явным флагом offline (без утверждений о синхронизации).
 */
export function useHistoryList(pageLimit = 20) {
  const [items, setItems] = useState<HistoryItem[]>(() => loadHistory());
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (nextOffset: number, append: boolean) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      try {
        const r = await api<ServerHistory>(
          `/api/lots/history?limit=${pageLimit}&offset=${nextOffset}`,
        );
        // Сервер может вернуть created_at: null — нормализуем к строке.
        const list = (Array.isArray(r.items) ? r.items : []).map((i) => ({
          ...i,
          created_at: typeof i.created_at === "string" ? i.created_at : "",
        }));
        setItems((prev) => (append ? [...prev, ...list] : list));
        setTotal(typeof r.total === "number" ? r.total : list.length);
        setOffset(nextOffset);
        setOffline(false);
        setError(null);
        if (!append) saveHistory(list);
      } catch (e) {
        // Безопасное сообщение + локальная копия как явный fallback.
        setError(e instanceof ApiError ? e.message : SAFE_HISTORY_ERROR);
        if (!append) {
          setItems(loadHistory());
          setTotal(null);
        }
        setOffline(true);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [pageLimit],
  );

  useEffect(() => {
    void load(0, false);
  }, [load]);

  const loadMore = useCallback(() => {
    void load(offset + pageLimit, true);
  }, [load, offset, pageLimit]);

  const hasMore = total !== null && items.length < total;

  return { items, total, loading, loadingMore, offline, error, hasMore, loadMore, reload: () => load(0, false) };
}

/** Текущее пятичасовое окно: анализы, активные резервы и время обновления. */
export function useQuota() {
  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const refresh = () => api<unknown>("/api/account/quota")
      .then((r) => {
        if (active) setQuota(toQuota(r));
      })
      .catch(() => {
        if (active) setQuota(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    void refresh();
    const timer = setInterval(refresh, 30_000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return { quota, loading };
}

/** Локальные данные кабинета: сохранённые лоты и скачанные документы. */
export function useLocalCabinet() {
  const [savedLots, setSavedLots] = useState<SavedLot[]>(() => loadSavedLots());
  const [documents, setDocuments] = useState<PreparedDocument[]>(() => loadDocuments());

  const refresh = useCallback(() => {
    setSavedLots(loadSavedLots());
    setDocuments(loadDocuments());
  }, []);

  useEffect(() => {
    let active = true;
    void hydrateCabinetFromServer()
      .then((state) => {
        if (!active) return;
        setSavedLots(state.savedLots);
        setDocuments(state.documents);
      })
      .catch(() => {
        // Local data remains available while offline.
      });
    return () => {
      active = false;
    };
  }, []);

  return { savedLots, documents, refresh };
}
